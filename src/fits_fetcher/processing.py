"""Processing chain for one downloaded science image (Section 8).

Order (REQ-41): read → linearise (REQ-36) → star-core repair (REQ-37–43) → cutout (REQ-25, REQ-58)
→ NaN to 0 (REQ-22) → header (S-22, REQ-23, REQ-42, REQ-54) → compatibility check (REQ-49) → save.
Reprojection (REQ-24) comes in a later build; `Options.reproject` is recorded as off.
"""
from __future__ import annotations

import datetime as dt
import math
import os
import textwrap
import warnings
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np
from astropy.io import fits
from astropy.stats import sigma_clipped_stats
from astropy.wcs import WCS, FITSFixedWarning
from scipy import ndimage

from fits_fetcher import __version__, footprint
from fits_fetcher.archives.base import Fetched, Product, Target

# Header keywords carried over from the archive file when present (S-22): instrument set-up, exposure,
# dates, units, target and programme, and the photometric calibration that makes the values meaningful.
KEEP = ("TELESCOP", "INSTRUME", "DETECTOR", "FILTER", "FILTER1", "FILTER2", "PUPIL", "EXPTIME", "TEXPTIME",
        "XPOSURE", "EFFEXPTM", "DATE-OBS", "TIME-OBS", "DATE-BEG", "DATE-END", "EXPSTART", "EXPEND", "BUNIT",
        "TARGNAME", "PROPOSID", "PROGRAM", "OBSERVTN", "VISIT", "PHOTMODE", "PHOTFLAM", "PHOTFNU", "PHOTPLAM",
        "PHOTBW", "PHOTZPT", "PHOTMJSR", "PHOTUJA2", "PIXAR_SR", "PIXAR_A2", "MAGZP", "MAGZPUNC")

# REQ-67: a hole next to a bright star is recognised by its edge. Measured on M37 (Pan-STARRS i, z): the brightest
# tenth of the pixels within 3 px of star holes lay 102-523 sigma above the sky, blank blocks and borders 2-6 sigma.
RIM_WIDTH_PX = 3
BRIGHT_RIM_SIGMA = 25.0
BRIGHT_RIM_PERCENTILE = 90

_DTYPES = {8: ">u1", 16: ">i2", 32: ">i4", 64: ">i8", -32: ">f4", -64: ">f8"}


class ProcessingError(Exception):
    """The image couldn't be processed or failed the compatibility check (REQ-49)."""


@dataclass(frozen=True)
class Options:
    """Processing settings for one download (REQ-61); recorded in each output's header (REQ-54)."""
    star_repair: bool = True
    repair_max_area: int = 2000
    repair_max_area_bright: int = 50_000  # REQ-67: holes next to bright stars
    cutout: bool = False
    box_arcmin: float = 10.0
    reproject: bool = False  # REQ-24: not built yet

    def for_product(self, product: Product) -> Options:
        if product.parts or product.cut:  # already cut: Pan-STARRS box (REQ-68), off-centre shared area (REQ-71)
            return replace(self, cutout=False)
        return replace(self, cutout=True) if product.is_mosaic else self  # mosaics are always cut (REQ-58)

    def cards(self) -> list[tuple[str, object, str]]:
        return [("FFREPAIR", self.star_repair, "FITS-fetcher star-core repair applied"),
                ("FFREPMAX", self.repair_max_area, "[px] largest hole repaired"),
                ("FFREPMXB", self.repair_max_area_bright, "[px] largest hole next to a bright star"),
                ("FFCUTOUT", self.cutout, "cut around the object"),
                ("FFCUTSZ", round(self.box_arcmin, 3) if self.cutout else 0.0, "[arcmin] cutout box size"),
                ("FFREPROJ", self.reproject, "reprojected onto a common grid")]

    def matches(self, header: fits.Header) -> bool:
        """Was an existing output made with these settings? (REQ-54)"""
        for key, value, _ in self.cards():
            if key in ("FFREPMAX", "FFREPMXB") and not self.star_repair:
                continue
            have = header.get(key)
            if have is None:
                return False
            if isinstance(value, float) and not isinstance(value, bool):
                if not math.isclose(float(have), value, abs_tol=1e-3):
                    return False
            elif have != value:
                return False
        return True


@dataclass
class Result:
    data: np.ndarray
    header: fits.Header
    warnings: list[str]


# ---------- steps ----------
def read_science(f: Fetched) -> np.ndarray:
    """The science array as native-order float32 with any BSCALE/BZERO applied."""
    if f.stitch:
        return stitch(f)
    if f.hdu is not None:
        with fits.open(f.path) as h:
            return np.asarray(h[f.hdu].data, dtype=np.float32)
    h = f.header
    if h.get("NAXIS") != 2:
        raise ProcessingError(f"Expected a 2-D image, found NAXIS = {h.get('NAXIS')}.")
    ny, nx = h["NAXIS2"], h["NAXIS1"]
    raw = np.fromfile(f.path, dtype=_DTYPES[h["BITPIX"]], count=nx * ny)
    if raw.size != nx * ny:
        raise ProcessingError("The downloaded data are shorter than the header says.")
    raw = raw.reshape(ny, nx)
    if h["BITPIX"] == -32:
        data = raw.byteswap(inplace=True).view(np.float32)  # no copy: these can be gigabytes
    else:
        data = raw.astype(np.float32)
        if "BLANK" in h and h["BITPIX"] > 0:
            data[raw == h["BLANK"]] = np.nan
    scale, zero = h.get("BSCALE", 1.0), h.get("BZERO", 0.0)
    if (scale, zero) != (1.0, 0.0):
        data *= np.float32(scale)
        data += np.float32(zero)
    return data


def stitch(f: Fetched) -> np.ndarray:
    """REQ-68: paste pieces on one pixel lattice into a canvas the size of `f.header`.

    Each piece is linearised first (REQ-36: every Pan-STARRS skycell has its own BOFFSET/BSOFTEN). Where pieces
    overlap, a pixel comes from the piece it lies deepest inside (farthest from that piece's edge); blank pixels
    (NaN or 0) never win, so a hole in one piece is filled from its neighbour where that has data.
    """
    ny, nx = f.header["NAXIS2"], f.header["NAXIS1"]
    canvas = np.full((ny, nx), np.nan, dtype=np.float32)
    depth = np.full((ny, nx), -1, dtype=np.int16)
    for path, hdu, ox, oy in f.stitch:
        with fits.open(path) as h:
            part = np.asarray(h[hdu].data, dtype=np.float32)
            linearise(part, h[hdu].header)
        py, px = part.shape
        cx0, cy0, cx1, cy1 = max(ox, 0), max(oy, 0), min(ox + px, nx), min(oy + py, ny)
        if cx0 >= cx1 or cy0 >= cy1:
            continue
        piece = part[cy0 - oy:cy1 - oy, cx0 - ox:cx1 - ox]
        u, v = np.arange(cx0 - ox, cx1 - ox), np.arange(cy0 - oy, cy1 - oy)
        d = np.minimum.outer(np.minimum(v, py - 1 - v), np.minimum(u, px - 1 - u)).astype(np.int16)
        win = (slice(cy0, cy1), slice(cx0, cx1))
        take = np.isfinite(piece) & (piece != 0) & (d > depth[win])
        canvas[win][take] = piece[take]
        depth[win][take] = d[take]
        del part, piece, d, take
    return canvas


def linearise(data: np.ndarray, header: fits.Header) -> str | None:
    """REQ-36: undo Pan-STARRS asinh encoding in place (formula confirmed in verification step 06)."""
    if "BSOFTEN" not in header or "BOFFSET" not in header:
        return None
    a = 2.5 / math.log(10)
    data[...] = header["BOFFSET"] + header["BSOFTEN"] * 2 * np.sinh(data.astype(np.float64) / a)
    return "Linearised from asinh encoding: BOFFSET + BSOFTEN * 2 * sinh(x / (2.5 / ln 10))."


@dataclass
class Repaired:
    regions: int = 0
    pixels: int = 0
    bright: int = 0  # of which large holes next to bright stars (REQ-67)


def repair_star_cores(data: np.ndarray, max_area: int, max_area_bright: int = 0) -> Repaired:
    """REQ-37–40, REQ-67: fill enclosed holes (NaN or exactly 0) from the rim inward.

    Holes are 8-connected regions of candidate pixels. A region touching the image edge is left alone (REQ-38).
    Because regions are 8-connected, every pixel bordering a region is valid, so a region that doesn't touch the
    edge is fully surrounded. Regions up to `max_area` are filled; larger ones up to `max_area_bright` only if
    their edge is bright starlight (REQ-67).
    """
    bad = ~np.isfinite(data) | (data == 0)
    done = Repaired()
    if not bad.any():
        return done
    labels, n = ndimage.label(bad, structure=np.ones((3, 3), dtype=bool))
    sizes = np.bincount(labels.ravel())
    ny, nx = data.shape
    sky = None
    for i, sl in enumerate(ndimage.find_objects(labels), start=1):
        if sl is None or sizes[i] > max(max_area, max_area_bright):
            continue
        ys, xs = sl
        if ys.start == 0 or xs.start == 0 or ys.stop == ny or xs.stop == nx:
            continue
        large = sizes[i] > max_area
        if large:
            if sky is None:  # sky level and noise, measured once and only when needed
                _, med, sigma = sigma_clipped_stats(data[~bad][::37], sigma=3, maxiters=5)
                sky = (float(med), float(sigma))
            if not _next_to_bright_star(data, labels, i, sl, bad, sky):
                continue
        win = (slice(ys.start - 1, ys.stop + 1), slice(xs.start - 1, xs.stop + 1))
        _fill(data[win], labels[win] == i)
        done.regions += 1
        done.pixels += int(sizes[i])
        done.bright += large
    return done


def _next_to_bright_star(data, labels, i, sl, bad, sky: tuple[float, float]) -> bool:
    """REQ-67: are the brightest pixels around hole `i` far above the sky?"""
    ys, xs = sl
    r = RIM_WIDTH_PX + 1
    win = (slice(max(ys.start - r, 0), ys.stop + r), slice(max(xs.start - r, 0), xs.stop + r))
    hole = labels[win] == i
    rim = ndimage.binary_dilation(hole, np.ones((3, 3), dtype=bool), iterations=RIM_WIDTH_PX) & ~hole & ~bad[win]
    if not rim.any():
        return False
    med, sigma = sky
    return float(np.percentile(data[win][rim], BRIGHT_RIM_PERCENTILE)) >= med + BRIGHT_RIM_SIGMA * sigma


def _fill(win: np.ndarray, hole: np.ndarray) -> None:
    """REQ-39: each pass sets every hole pixel touching a valid pixel to the mean of its valid 8-neighbours,
    using the previous pass's values, so the fill is symmetric (unlike PixelClip's raster order)."""
    valid = ~hole & np.isfinite(win) & (win != 0)
    remaining = hole.copy()
    h, w = win.shape
    while remaining.any():
        vals = np.pad(np.where(valid, win, 0.0).astype(np.float64), 1)
        cnt = np.pad(valid.astype(np.int16), 1)
        s = np.zeros((h, w))
        c = np.zeros((h, w), dtype=np.int16)
        for dy in (0, 1, 2):
            for dx in (0, 1, 2):
                if dy == dx == 1:
                    continue
                s += vals[dy:dy + h, dx:dx + w]
                c += cnt[dy:dy + h, dx:dx + w]
        front = remaining & (c > 0)
        if not front.any():
            break  # can't happen for an enclosed region; guards against an endless loop
        win[front] = s[front] / c[front]
        valid |= front
        remaining &= ~front


def nan_to_zero(data: np.ndarray) -> int:
    """REQ-22: always last, so zeros are never interpolated into real data."""
    bad = ~np.isfinite(data)
    n = int(bad.sum())
    data[bad] = 0
    return n


def _wcs(header: fits.Header) -> WCS:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", FITSFixedWarning)
        return WCS(header).celestial


# ---------- the chain ----------
def process(f: Fetched, product: Product, target: Target, options: Options) -> Result:
    options = options.for_product(product)
    data = read_science(f)
    history = list(f.notes)
    notes: list[str] = []

    if (note := linearise(data, f.header)) is not None:
        history.append(note)

    if options.star_repair:
        rep = repair_star_cores(data, options.repair_max_area, options.repair_max_area_bright)
        history.append(f"Star-core repair: {rep.regions} regions, {rep.pixels} pixels filled (limit {options.repair_max_area} px; "
                       f"{rep.bright} larger holes next to bright stars, limit {options.repair_max_area_bright} px). "
                       "Filled cores are estimates, not measurements; don't use them for photometry.")
    else:
        rep = Repaired()

    wcs = _wcs(f.header)
    box, clipped = f.box, f.box_clipped
    if options.cutout and box is None:
        try:
            box, clipped = footprint.pixel_box(f.header, target.ra, target.dec, options.box_arcmin, data.shape)
        except ValueError as e:
            raise ProcessingError(str(e)) from e
    if box is not None:
        x0, x1, y0, y1 = box
        data = data[y0:y1, x0:x1].copy()
        wcs = wcs[y0:y1, x0:x1]
        if product.cut:
            history.append(f"Cut to the area all filters of this set share ({product.spot}): {x1 - x0} x {y1 - y0} px.")
            if clipped:
                notes.append("The shared area ran past this image's edge, so its box is smaller than the other filters'.")
        else:
            history.append(f"Cut around {target.matched_id or 'the object'}: {x1 - x0} x {y1 - y0} px "
                           f"({options.box_arcmin:.1f} arcmin box).")
            if clipped:
                notes.append("The box around the object ran past the image edge, so part of the object is missing.")

    zeros = nan_to_zero(data)
    if zeros:
        history.append(f"{zeros} blank (NaN) pixels set to 0.")

    header = build_header(f, product, target, wcs, options, history, rep)
    return Result(data, header, notes)


def build_header(f: Fetched, product: Product, target: Target, wcs: WCS, options: Options,
                 history: list[str], repaired: Repaired) -> fits.Header:
    h = fits.Header()
    h.extend(wcs.to_header(relax=True).cards)
    for key in KEEP:
        for src in (f.header, f.primary):
            if key in src and src[key] not in ("", None):
                h[key] = (src[key], src.comments[key])
                break
    h["OBJECT"] = (target.matched_id or target.query, "object searched for in FITS-fetcher")
    h["FILTER"] = (product.filter, "filter")
    h.setdefault("TELESCOP", product.telescope)
    h.setdefault("INSTRUME", product.instrument)
    if "EXPTIME" not in h and product.exptime_s:
        h["EXPTIME"] = (product.exptime_s, "[s] exposure time")
    if "DATE-OBS" not in h and product.obs_date:
        h["DATE-OBS"] = product.obs_date

    # Provenance (REQ-23) and processing settings (REQ-42, REQ-54).
    today = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    h["FFVER"] = (__version__, "FITS-fetcher version")
    h["FFDATE"] = (today, "UTC download date")
    h["FFARCH"] = (product.archive, "source archive")
    h["FFCOLL"] = (product.collection, "archive collection")
    h["FFOBSID"] = (product.obs_id, "archive observation ID")
    for key, value, comment in options.cards():
        h[key] = (value, comment)
    h["FFNREG"] = (repaired.regions, "star-core regions filled")
    h["FFNPIX"] = (repaired.pixels, "star-core pixels filled")
    h["FFNBRGT"] = (repaired.bright, "of which large holes next to bright stars")
    h.add_history(f"Downloaded {today} UTC by FITS-fetcher {__version__} from:")
    for part in textwrap.wrap(f.url or product.url, 70, break_on_hyphens=False):
        h.add_history(part)
    for line in history:
        for part in textwrap.wrap(line, 70):
            h.add_history(part)
    return h


# ---------- saving ----------
def check_compatible(path: Path) -> list[str]:
    """REQ-49: problems that would stop PixInsight or Siril opening the file directly."""
    problems = []
    with fits.open(path) as hdul:
        if len(hdul) != 1:
            problems.append(f"{len(hdul)} HDUs instead of one")
        h = hdul[0].header
        if isinstance(hdul[0], fits.CompImageHDU) or "ZIMAGE" in h:
            problems.append("compressed")
        if h.get("BITPIX") != -32:
            problems.append(f"BITPIX is {h.get('BITPIX')}, not -32")
        if "BSCALE" in h or "BZERO" in h:
            problems.append("has BSCALE/BZERO scaling")
        if h.get("NAXIS") != 2:
            problems.append(f"NAXIS is {h.get('NAXIS')}, not 2")
        try:
            if not _wcs(h).has_celestial:
                problems.append("no celestial WCS")
        except Exception as e:
            problems.append(f"unreadable WCS ({e})")
    return problems


def save(result: Result, path: Path) -> None:
    """Write, check (REQ-49), then move into place; a file that fails the check is not saved."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.stem + ".partial.fits")
    fits.PrimaryHDU(result.data.astype(np.float32, copy=False), result.header).writeto(
        tmp, overwrite=True, output_verify="fix")
    problems = check_compatible(tmp)
    if problems:
        tmp.unlink(missing_ok=True)
        raise ProcessingError("Output failed the PixInsight/Siril compatibility check: " + "; ".join(problems))
    os.replace(tmp, path)


def existing_matches(path: Path, options: Options) -> bool:
    """REQ-54: skip a product only if its output exists and was made with the same settings."""
    try:
        return options.matches(fits.getheader(path))
    except (OSError, ValueError):
        return False
