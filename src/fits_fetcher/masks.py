"""Data masks saved next to each image (REQ-101 to REQ-103).

A saved image stores blank pixels as 0 (REQ-22), and afterwards a 0 can't be told from real sky, nor a chip gap
from the blank border. The mask is made while the app still knows which pixels are blank:
- `DATA` (primary HDU): 255 where the image has real data (repaired star cores count as data), 0 where blank.
- `GAPS` (second HDU): 255 on blank strips inside the camera's field, such as the gap between two CCDs, found by
  closing the DATA layer over strips up to GAP_MAX_ARCSEC wide.
Both are 8-bit, so PixInsight and Siril read 255 as 1.0. Images on one pixel grid (REQ-60) also get a combined
`Grid_<grid>_mask.fits` in their set folder: data in every filter saved so far, and that mask's gaps.
"""
from __future__ import annotations

import math
import os
import warnings
from collections import Counter
from pathlib import Path

import numpy as np
from astropy.io import fits
from astropy.wcs import WCS, FITSFixedWarning
from astropy.wcs.utils import proj_plane_pixel_scales
from scipy import ndimage

from fits_fetcher import __version__
from fits_fetcher.output import safe

MASK_SUFFIX = "_mask.fits"
ON = 255
# Widest blank strip counted as a gap: WFC3/UVIS's chip gap is 1.2-1.6″ (NGC 976, verification 24), ACS/WFC's about
# 2.5″. NIRCam's ~44″ module gap is far wider and has its own chip (REQ-84).
GAP_MAX_ARCSEC = 3.5


def mask_path(image: Path) -> Path:
    return image.with_name(image.stem + MASK_SUFFIX)


def grid_mask_path(folder: Path, grid_name: str) -> Path:
    return folder / f"Grid_{safe(grid_name)}{MASK_SUFFIX}"


def _wcs(header: fits.Header) -> WCS:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", FITSFixedWarning)
        return WCS(header).celestial


def pixel_scale_arcsec(header: fits.Header) -> float:
    return float(np.mean(proj_plane_pixel_scales(_wcs(header)))) * 3600


def gap_radius_px(scale_arcsec: float) -> int:
    """Half-size of the closing square: closes axis-aligned strips up to 2r px wide, diagonal ones wider."""
    return math.ceil(GAP_MAX_ARCSEC / scale_arcsec / 2) + 1


def gap_layer(data: np.ndarray, scale_arcsec: float) -> np.ndarray:
    """Blank pixels inside the field: those a closing of `data` (True = data) fills, in pieces big enough to be a
    strip rather than the rounding of a corner. Running max/min filters keep it fast on mosaic-sized images.
    Outside the array counts as blank, so the blank border isn't mistaken for a gap."""
    r = gap_radius_px(scale_arcsec)
    size = 2 * r + 1
    # Padded with blank: a gap reaching a narrow border (REQ-75 trims to 16 px) is kept to the field's edge.
    closed = np.pad(data.astype(np.uint8), r + 1)
    for f in (ndimage.maximum_filter1d, ndimage.minimum_filter1d):
        for axis in (0, 1):
            closed = f(closed, size, axis=axis, mode="constant", cval=0)
    gaps = closed[r + 1:-r - 1, r + 1:-r - 1].astype(bool) & ~data
    del closed
    labels, n = ndimage.label(gaps, structure=np.ones((3, 3), dtype=bool))
    if not n:
        return gaps
    keep = np.bincount(labels.ravel()) >= r * r
    keep[0] = False
    return keep[labels]


def write_mask(path: Path, data: np.ndarray, image_header: fits.Header, image_name: str, history: list[str]) -> int:
    """Write a DATA + GAPS mask for an image. `data` is True where the image has real data. Returns gap pixels."""
    scale = pixel_scale_arcsec(image_header)
    gaps = gap_layer(data, scale)
    wcs_cards = _wcs(image_header).to_header(relax=True)
    h = fits.Header()
    h["EXTNAME"] = ("DATA", "255 = real data, 0 = blank")
    h.extend(wcs_cards.cards)
    for key in ("OBJECT", "TELESCOP", "INSTRUME", "FILTER", "FFARCH", "FFOBSID", "FFGRID", "FFGRIDNM", "FFNIMG"):
        if key in image_header:
            h[key] = (image_header[key], image_header.comments[key])
    h["FFIMAGE"] = (image_name, "image this mask belongs to")
    h["FFVER"] = (__version__, "FITS-fetcher version")
    h["FFGAPMAX"] = (GAP_MAX_ARCSEC, "[arcsec] widest blank strip counted as a gap")
    h["FFGAPPX"] = (int(gaps.sum()), "pixels in the GAPS layer")
    h.add_history("FITS-fetcher data mask. DATA: 255 where the image has real data (repaired star cores")
    h.add_history("included), 0 where it is blank. GAPS (second HDU): 255 on blank strips inside the")
    h.add_history(f"camera field up to {GAP_MAX_ARCSEC} arcsec wide, such as the gap between CCDs.")
    for line in history:
        h.add_history(line)
    g = fits.Header()
    g["EXTNAME"] = ("GAPS", "255 = blank strip inside the field")
    g.extend(wcs_cards.cards)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.stem + ".partial.fits")
    fits.HDUList([fits.PrimaryHDU(data.astype(np.uint8) * ON, h),
                  fits.ImageHDU(gaps.astype(np.uint8) * ON, g)]).writeto(tmp, overwrite=True)
    os.replace(tmp, path)
    return int(gaps.sum())


def has_mask(image: Path) -> bool:
    return mask_path(image).exists()


def combine_grid(folder: Path, grid: str, grid_name: str) -> Path | None:
    """REQ-103: the mask of data present in every image on one grid in `folder` (two or more needed). Masks of a
    different size (an image whose box grew past its grid's, REQ-75) are left out and named in the HISTORY."""
    found = []
    for p in sorted(folder.glob(f"*{MASK_SUFFIX}")):
        if p.name.startswith("Grid_"):
            continue
        try:
            h = fits.getheader(p)
        except (OSError, ValueError):
            continue
        if h.get("FFGRID") == grid:
            found.append((p, h))
    target = grid_mask_path(folder, grid_name)
    if len(found) < 2:
        return None
    shapes = {p: (h["NAXIS2"], h["NAXIS1"]) for p, h in found}
    shape = Counter(shapes.values()).most_common(1)[0][0]
    used = [(p, h) for p, h in found if shapes[p] == shape]
    left_out = [p.name for p, _ in found if shapes[p] != shape]
    if len(used) < 2:
        return None
    combined = np.ones(shape, dtype=bool)
    for p, _ in used:
        with fits.open(p) as hdul:
            combined &= hdul[0].data > 0
    ref = used[0][1]
    lines = [f"Data present in all {len(used)} images on this grid:"] + [f"  {h.get('FFIMAGE', p.name)}" for p, h in used]
    if left_out:
        lines += ["Left out (a different size; needs registration):"] + [f"  {n}" for n in left_out]
    header = ref.copy()
    header["FFIMAGE"] = ("(all images on this grid)", "images this mask belongs to")
    header["FFGRIDNM"] = (grid_name, "pixel grid (REQ-60)")
    header["FFNIMG"] = (len(used), "images combined")
    for key in ("FILTER", "FFOBSID", "FFGAPPX"):
        header.remove(key, ignore_missing=True)
    header.remove("HISTORY", ignore_missing=True, remove_all=True)
    write_mask(target, combined, header, header["FFIMAGE"], lines)
    return target
