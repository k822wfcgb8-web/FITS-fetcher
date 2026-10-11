"""MAST module: HST (pipeline collection only, REQ-55), JWST and Pan-STARRS combined images.

Selection rules come from verification steps 01, 05 and 07 (verify/FINDINGS.md) and REQ-58:
- Query level 3 public science images, then keep only allow-listed instruments (drops TESS, STIS acquisitions…).
- HST: Hubble Advanced Products single-visit images (`hst_<prop>_<visit>_…`) by default; multi-visit skycell
  mosaics (`hst_skycell-…_all`) only when `hst_show_mosaics` is on, always cut around the object. Classic
  pipeline products, white-light `_total_` images and coarse-grid IR mosaics (`_coarse-all`, 0.12" instead of
  the shared 0.04" grid) are never offered.
- File addresses are built from the observation ID instead of calling get_product_list, which took 56 of
  60 s for M51 (26,862 file entries for 168 observations). Patterns checked against MAST on 2026-10-10:
  HST ACS/WFC and WFC3/UVIS `<obs_id>_drc.fits`, other HST `<obs_id>_drz.fits`, JWST `<obs_id>_i2d.fits`,
  PS1 `rings.v3.skycell/<proj>/<sub>/<obs_id>.unconv.fits` on ps1images.stsci.edu.
- Download (REQ-57): HST and JWST files are read with range requests and only the `SCI` extension is fetched;
  for HST mosaics only the rows of the box around the object. PS1 stacks are one compressed image, fetched whole.
- Pan-STARRS (REQ-68): a box 1.5x the object's size, stitched from the skycells it needs. Skycells of one
  projection cell share one pixel lattice (verified for M46: same CRVAL, CDELT and PC; CRPIX offsets in whole
  pixels), so they are pasted together without resampling. PS1 has its own small query sized to the box, run
  in parallel with the main query, which stays at the object's centre. For each skycell the app fetches either
  a cutout of just the part inside the box (the PS1 cutout service returns linear 32-bit floats on the same
  pixel grid, checked 2026-10-10) or the whole compressed file, whichever is smaller.
- Objects inside a large object (REQ-70) and off-centre sets (REQ-71) come from one shared query of the object's
  disc, capped at INSIDE_MAX_RADIUS_DEG. Off-centre candidates always include HST mosaics (most same-grid groups
  away from the centre exist only as mosaics; M35, verification step 16) and are cut to the area their filters
  share: single-visit images are fetched whole and cut, mosaics only for the rows of that area.
"""
from __future__ import annotations

import logging
import math
import re
import threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from urllib.parse import urlencode

import astropy.units as u
from astropy.coordinates import SkyCoord
from astropy.time import Time
from astropy.io import fits
from astroquery.mast import Observations

from fits_fetcher import filters, footprint
from fits_fetcher.archives.base import Archive, ArchiveError, Fetched, InsideGroup, Product, Target
from fits_fetcher.transfer import Progress, Transfer, TransferError

log = logging.getLogger(__name__)
DOWNLOAD = "https://mast.stsci.edu/api/v0.1/Download/file?uri="

INSTRUMENTS = {
    "HST": ("ACS/WFC", "ACS/HRC", "WFC3/UVIS", "WFC3/IR", "WFPC2", "NICMOS"),
    "JWST": ("NIRCAM/IMAGE", "MIRI/IMAGE", "NIRISS/IMAGE"),
    "PS1": ("GPC1",),
}

# Nominal output pixel scales (arcsec) of the combined products, for display and REQ-26.
PIXEL_SCALE = {
    "ACS/WFC": 0.05, "ACS/HRC": 0.025, "WFC3/UVIS": 0.04, "WFC3/IR": 0.128, "WFPC2": 0.1,
    "NICMOS/NIC1": 0.043, "NICMOS/NIC2": 0.075, "NICMOS/NIC3": 0.2,
    "MIRI/IMAGE": 0.11, "NIRISS/IMAGE": 0.066, "GPC1": 0.25,
}

PS1_IMAGES = "https://ps1images.stsci.edu/rings.v3.skycell"
PS1_CUTOUT = "https://ps1images.stsci.edu/cgi-bin/fitscut.cgi"
PS1_STACK_BYTES = 68_000_000  # a whole compressed PS1 stack file (verification step 05)
DRC_INSTRUMENTS = ("ACS/WFC", "WFC3/UVIS")  # CTE-corrected products; everything else is _drz

# HST multi-visit mosaics: one skycell is about 21,258 px wide at 0.04"/px (verified on M51's skycell).
SKYCELL_WIDTH_PX = 21258
MOSAIC_PIXEL_SCALE = 0.04
# Extra mosaic rows fetched above and below the box, so star cores on the box edge are still enclosed
# by valid pixels and can be repaired (REQ-38) before the box is cut.
MOSAIC_MARGIN_PX = 64

PS1_PIXEL_SCALE = 0.25
PS1_LATTICE_KEYS = ("CRVAL1", "CRVAL2", "CDELT1", "CDELT2", "PC001001", "PC001002", "PC002001", "PC002002")
# Keywords of a compressed skycell's table header that don't belong in the image we build (REQ-68).
_NOT_IMAGE = re.compile(r"^(XTENSION|BITPIX|NAXIS\d*|PCOUNT|GCOUNT|TFIELDS|TTYPE\d+|TFORM\d+|TUNIT\d+|THEAP|Z\w*|"
                        r"EXTNAME|CHECKSUM|DATASUM|BOFFSET|BSOFTEN|BSCALE|BZERO|BLANK)$")
# REQ-70 search radius cap: at 0.25 deg MAST already took 35 s for M42 (5,222 rows) on 2026-10-10.
INSIDE_MAX_RADIUS_DEG = 0.25


def hst_family(obs_id: str) -> str:
    """'mosaic', 'single-visit' or 'classic' (REQ-58)."""
    obs_id = obs_id.lower()
    if obs_id.startswith("hst_skycell"):
        return "mosaic"
    if obs_id.startswith("hst_"):
        return "single-visit"
    return "classic"


def grid_key(collection: str, filt: str, obs_id: str) -> str:
    """Name of the pixel grid an image is on; same name = stacks without registration (REQ-60, verification 12).

    HST single-visit images share a grid per visit and detector, HST mosaics per skycell, PS1 stacks per skycell.
    JWST and anything unrecognised get "" (no claim).
    """
    if collection == "PS1":
        return "PS1 skycell " + ".".join(obs_id.split(".")[3:5])
    if collection != "HST":
        return ""
    parts = obs_id.lower().split("_")
    family = hst_family(obs_id)
    if family == "mosaic":
        return "HST " + parts[1].replace("-", " ")  # "HST skycell p2261x11y16"
    if family != "single-visit" or filt.lower() not in parts:
        return ""
    rest = [t for t in parts[3:-1] if t != filt.lower()]  # instrument and detector, e.g. wfc3 uvis
    return f"HST visit {parts[1]}_{parts[2]} {'/'.join(rest).upper()}"


def ps1_cell(obs_id: str) -> str:
    """Projection cell of a PS1 skycell ID: 'rings.v3.skycell.0994.022.stk.r' → '0994'."""
    return obs_id.split(".")[3]


def _whole_offset(a, b) -> bool:
    """Do two headers on one lattice differ by whole pixels?"""
    return all(abs((a[k] - b[k]) - round(a[k] - b[k])) < 1e-6 for k in ("CRPIX1", "CRPIX2"))


def _allowed(collection: str, instrument: str) -> bool:
    return any(instrument.upper().startswith(p) for p in INSTRUMENTS.get(collection, ()))


def _pixel_scale(instrument: str, wavelength_um: float | None) -> float | None:
    if instrument.upper().startswith("NIRCAM"):
        return 0.031 if (wavelength_um or 0) < 2.4 else 0.063
    for key, scale in PIXEL_SCALE.items():
        if instrument.upper().startswith(key):
            return scale
    return None


def _http(uri: str) -> str:
    if not uri:
        return ""
    return uri if uri.startswith("http") else DOWNLOAD + uri


def file_url(collection: str, instrument: str, obs_id: str) -> str:
    if collection == "PS1":
        proj, sub = obs_id.split(".")[3:5]  # rings.v3.skycell.<proj>.<sub>.stk.<band>
        return f"{PS1_IMAGES}/{proj}/{sub}/{obs_id}.unconv.fits"
    if collection == "JWST":
        return f"{DOWNLOAD}mast:JWST/product/{obs_id}_i2d.fits"
    suffix = "drc" if instrument.upper().startswith(DRC_INSTRUMENTS) else "drz"
    return f"{DOWNLOAD}mast:HST/product/{obs_id}_{suffix}.fits"


def _text(v) -> str:
    s = str(v)
    return "" if s in ("--", "None", "nan") else s


def _float(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f != f else f


class MastArchive(Archive):
    name = "MAST"

    def __init__(self, settings):
        super().__init__(settings)
        self._around_lock = threading.Lock()
        self._around_cache: dict[tuple, list] = {}

    def _collections(self) -> list[str]:
        return [c for c in self.settings.mast_collections if c in INSTRUMENTS]

    def _query(self, target: Target, radius_deg: float, collections: list[str]):
        try:
            return Observations.query_criteria(
                coordinates=SkyCoord(target.ra * u.deg, target.dec * u.deg), radius=radius_deg * u.deg,
                obs_collection=collections, dataproduct_type="image", calib_level=[3],
                intentType="science", dataRights="PUBLIC")
        except Exception as e:
            raise ArchiveError(f"MAST search failed: {e}") from e

    def _selected(self, row, collections: list[str], mosaics: bool | None = None) -> bool:
        coll = _text(row["obs_collection"])
        return (coll in collections and _allowed(coll, _text(row["instrument_name"]))
                and self._wanted_family(row, mosaics) and bool(filters.effective_filter(_text(row["filters"]))))

    def search(self, target: Target, radius_deg: float) -> list[Product]:
        pointed = [c for c in self._collections() if c != "PS1"]
        with ThreadPoolExecutor(2) as pool:  # the two queries run side by side: MAST answers in 3-35 s
            ps1 = pool.submit(self._ps1_products, target) if "PS1" in self._collections() else None
            rows = self._query(target, radius_deg, pointed) if pointed else []
            products = [self._product(r, target) for r in rows
                        if self._selected(r, pointed) and footprint.contains(_text(r["s_region"]), target.ra, target.dec)]
            return products + (ps1.result() if ps1 else [])

    # ---------- Pan-STARRS boxes (REQ-68) ----------
    def _ps1_box_arcmin(self, target: Target) -> float:
        return footprint.stitch_box_arcmin(target.size_arcmin, self.settings.cutout_default_arcmin)

    def _ps1_products(self, target: Target) -> list[Product]:
        side = self._ps1_box_arcmin(target)
        rows = [r for r in self._query(target, side / 60 / 2 * math.sqrt(2), ["PS1"]) if self._selected(r, ["PS1"])]
        by_filter = defaultdict(list)
        for r in rows:
            by_filter[filters.effective_filter(_text(r["filters"]))].append(r)
        pts = footprint.box_points(target.ra, target.dec, side / 60)
        out = []
        for rs in by_filter.values():
            centre = [r for r in rs if footprint.contains(_text(r["s_region"]), target.ra, target.dec)]
            if not centre:
                continue
            c = min(centre, key=lambda r: footprint.angular_sep_deg(
                _float(r["s_ra"]) or 0, _float(r["s_dec"]) or 0, target.ra, target.dec))
            cell = ps1_cell(_text(c["obs_id"]))
            same = [r for r in rs if ps1_cell(_text(r["obs_id"])) == cell]
            other = [r for r in rs if ps1_cell(_text(r["obs_id"])) != cell]
            needed, crosses = {}, False
            for pt in pts:
                cover = [r for r in same if footprint.contains(_text(r["s_region"]), *pt)]
                if cover:
                    needed.update((_text(r["obs_id"]), r) for r in cover)
                elif any(footprint.contains(_text(r["s_region"]), *pt) for r in other):
                    crosses = True
                    break
            if crosses:  # until reprojection (REQ-24) exists: the whole skycell holding the object
                out.append(replace(self._product(c, target),
                                   product_level="PS1 stack (whole skycell: the box crosses a projection-cell edge)"))
            else:
                out.append(self._ps1_box(c, [needed[k] for k in sorted(needed)], side, target))
        return out

    def _ps1_box(self, centre_row, rows, side: float, target: Target) -> Product:
        parts = [_text(r["obs_id"]) for r in rows]
        cell, band = ps1_cell(parts[0]), parts[0].rsplit(".", 1)[-1]
        subs = [o.split(".")[4] for o in parts]
        px = math.ceil(round(side * 60 / PS1_PIXEL_SCALE, 6))
        stitched = f", stitched from {len(parts)} skycells" if len(parts) > 1 else ""
        # Estimate: cutouts of the box (4 bytes a pixel) or whole files, whichever the fetch will choose.
        size = min(len(parts) * PS1_STACK_BYTES, int(px * px * 4 * 1.1))
        return replace(
            self._product(centre_row, target), obs_id=f"rings.v3.skycell.{cell}.{'+'.join(subs)}.stk.{band}",
            parts=parts, size_bytes=size, width=px, height=px,
            product_level=f"PS1 stack, {side:.1f}′ box around the object{stitched}",
            centre_ra=target.ra, centre_dec=target.dec, offset_arcmin=0.0, grid=f"PS1 projection cell {cell} box",
            coverage=footprint.coverage([_text(r["s_region"]) for r in rows], target.ra, target.dec, target.size_arcmin))

    # ---------- the object's disc: objects inside (REQ-70) and off-centre sets (REQ-71) ----------
    def _around(self, target: Target) -> list:
        """One query of the object's disc (capped), shared by inside() and elsewhere(): MAST took 30 s for M35."""
        pointed = [c for c in self._collections() if c != "PS1"]
        if not target.size_arcmin or not pointed:
            return []
        key = (target.ra, target.dec, target.size_arcmin, tuple(pointed))
        with self._around_lock:
            if key not in self._around_cache:
                radius = min(target.size_arcmin / 2 / 60, INSIDE_MAX_RADIUS_DEG)
                self._around_cache[key] = list(self._query(target, radius, pointed))
            return self._around_cache[key]

    def elsewhere(self, target: Target) -> list[Product]:
        pointed = [c for c in self._collections() if c != "PS1"]
        out = []
        for r in self._around(target):
            if self._selected(r, pointed, mosaics=True) and _float(r["s_ra"]) is not None:
                p = self._product(r, target, coverage=False)
                if p.grid and p.region:  # only images known to share a pixel grid can form a set (REQ-60)
                    out.append(p)
        return out

    def inside(self, target: Target, min_filters: int) -> list[InsideGroup]:
        pointed = [c for c in self._collections() if c != "PS1"]
        groups = defaultdict(list)
        for r in self._around(target):
            if (not self._selected(r, pointed) or _float(r["s_ra"]) is None
                    or footprint.contains(_text(r["s_region"]), target.ra, target.dec)):  # those are in the results
                continue
            groups[(_text(r["target_name"]), _text(r["instrument_name"]))].append(r)
        found = []
        for (name, inst), rs in groups.items():
            filts = {filters.effective_filter(_text(r["filters"])) for r in rs}
            if len(filts) < min_filters:
                continue
            order = sorted(filts, key=lambda f: filters.parse(f, inst)[0] or 99)
            found.append(InsideGroup(name=name, archive=self.name, instrument=inst, filters=order,
                                     ra=_float(rs[0]["s_ra"]), dec=_float(rs[0]["s_dec"])))
        return found

    def _wanted_family(self, row, mosaics: bool | None = None) -> bool:
        """REQ-58 product families; `mosaics` overrides the "Also show HST mosaics" switch (REQ-71)."""
        if _text(row["obs_collection"]) != "HST":
            return True
        obs_id = _text(row["obs_id"]).lower()
        if "_total_" in obs_id or obs_id.endswith("_coarse-all"):
            return False
        family = hst_family(obs_id)
        show_mosaics = self.settings.hst_show_mosaics if mosaics is None else mosaics
        return family == "single-visit" or (family == "mosaic" and show_mosaics)

    def _mosaic_box_arcmin(self, target: Target) -> float:
        return footprint.box_arcmin(target.size_arcmin, self.settings.cutout_default_arcmin)

    def fetch(self, product: Product, target: Target, transfer: Transfer, box_arcmin: float,
              progress: Progress) -> Fetched:
        if product.collection == "PS1" and product.parts:
            return self._fetch_ps1_box(product, target, transfer, progress)
        if product.collection == "PS1":
            path = transfer.fetch(product.url, progress=progress, suffix=".fits")
            with fits.open(path) as h:
                primary, header = h[0].header.copy(), h[1].header.copy()
            return Fetched(primary, header, path, hdu=1, files=[path])

        try:
            loc = transfer.locate_hdu(product.url, product.science_extension)
        except TransferError as e:
            # Some WFC3/UVIS and ACS/WFC images have no CTE-corrected _drc, only _drz (M35, verification step 16).
            if not (product.url.endswith("_drc.fits") and "HTTP 404" in str(e)):
                raise
            product = replace(product, url=product.url.removesuffix("_drc.fits") + "_drz.fits")
            loc = transfer.locate_hdu(product.url, product.science_extension)
        header = loc.header.copy()
        rows, cols = header["NAXIS2"], header["NAXIS1"]
        if product.cut:  # REQ-71: the area all filters of an off-centre set share
            try:
                (x0, x1, y0, y1), clipped = footprint.points_box(header, product.cut, (rows, cols))
            except ValueError as e:
                raise ArchiveError(str(e)) from e
        if not product.is_mosaic:
            path = transfer.fetch(product.url, loc.data_offset, loc.data_size, progress)
            if product.cut:
                return Fetched(loc.primary, header, path, files=[path], box=(x0, x1, y0, y1), box_clipped=clipped,
                               url=product.url)
            return Fetched(loc.primary, header, path, files=[path], url=product.url)

        # REQ-58: only the rows of the box around the object (plus a margin), each a full mosaic row.
        if not product.cut:
            (x0, x1, y0, y1), clipped = footprint.pixel_box(header, target.ra, target.dec, box_arcmin, (rows, cols))
        r0, r1 = max(0, y0 - MOSAIC_MARGIN_PX), min(rows, y1 + MOSAIC_MARGIN_PX)
        row_bytes = abs(header["BITPIX"]) // 8 * cols
        path = transfer.fetch(product.url, loc.data_offset + r0 * row_bytes, (r1 - r0) * row_bytes, progress)
        header["NAXIS2"] = r1 - r0
        header["CRPIX2"] = header["CRPIX2"] - r0
        return Fetched(loc.primary, header, path, files=[path], box=(x0, x1, y0 - r0, y1 - r0), box_clipped=clipped,
                       url=product.url, notes=[f"Rows {r0 + 1}-{r1} of the {cols} x {rows} px mosaic {product.obs_id} fetched."])

    def _fetch_ps1_box(self, product: Product, target: Target, transfer: Transfer, progress: Progress) -> Fetched:
        """REQ-68: read the skycells' headers, fetch the part of each inside the box, describe the canvas."""
        urls = [file_url("PS1", "GPC1", o) for o in product.parts]
        headers = [transfer.locate_hdu(url, 1).header for url in urls]  # headers only: a few KB each
        ci = urls.index(product.url) if product.url in urls else 0
        hc = headers[ci]
        for h, part in zip(headers, product.parts):
            same = all(math.isclose(float(h.get(k, 0)), float(hc.get(k, 0)), rel_tol=0, abs_tol=1e-9) for k in PS1_LATTICE_KEYS)
            if not (same and _whole_offset(hc, h)):
                raise ArchiveError(f"Pan-STARRS skycell {part} isn't on the same pixel grid; can't stitch without resampling.")
        (x0, x1, y0, y1), _ = footprint.pixel_box(hc, target.ra, target.dec, self._ps1_box_arcmin(target), None)

        # What to fetch from each skycell: the box's overlap as a cutout, or the whole file if that's smaller.
        plan = []
        for url, part, h in zip(urls, product.parts, headers):
            dx, dy = round(hc["CRPIX1"] - h["CRPIX1"]), round(hc["CRPIX2"] - h["CRPIX2"])
            u0, u1 = max(x0 - dx, 0), min(x1 - dx, h["ZNAXIS1"])
            v0, v1 = max(y0 - dy, 0), min(y1 - dy, h["ZNAXIS2"])
            if u0 >= u1 or v0 >= v1:
                continue
            w, ht = u1 - u0, v1 - v0
            if w * ht * 4 < PS1_STACK_BYTES:
                query = urlencode({"red": url.split("ps1images.stsci.edu", 1)[1], "format": "fits",
                                   "x": u0 + w // 2, "y": v0 + ht // 2, "size": f"{w},{ht}"})
                plan.append((f"{PS1_CUTOUT}?{query}", 0, w * ht * 4))
            else:
                plan.append((url, 1, PS1_STACK_BYTES))

        got: dict[str, tuple[int, int]] = {}

        def part_progress(url):
            def report(done, total):
                got[url] = (done, total)
                progress(sum(d for d, _ in got.values()), sum(got[u][1] if u in got else est for u, _, est in plan))
            return report

        stitch, paths = [], []
        for url, hdu, _ in plan:
            path = transfer.fetch(url, progress=part_progress(url), suffix=".fits")
            ph = fits.getheader(path, hdu)
            if not _whole_offset(hc, ph):
                raise ArchiveError("A Pan-STARRS cutout came back off the skycell's pixel grid.")
            stitch.append((path, hdu, round(hc["CRPIX1"] - ph["CRPIX1"]) - x0, round(hc["CRPIX2"] - ph["CRPIX2"]) - y0))
            paths.append(path)

        canvas = fits.Header([c for c in hc.cards if not _NOT_IMAGE.match(c.keyword)])
        canvas["NAXIS"], canvas["NAXIS1"], canvas["NAXIS2"] = 2, x1 - x0, y1 - y0
        canvas["CRPIX1"], canvas["CRPIX2"] = hc["CRPIX1"] - x0, hc["CRPIX2"] - y0
        cutouts = sum(1 for _, hdu, _ in plan if hdu == 0)
        subs = ", ".join(o.split(".")[4] for o in product.parts)
        note = (f"Box of {x1 - x0} x {y1 - y0} px around the object from Pan-STARRS skycell(s) {subs} of projection cell "
                f"{ps1_cell(product.parts[0])} ({cutouts} as cutouts), on one pixel grid with no resampling; "
                "each piece linear before stitching.")
        return Fetched(fits.Header(), canvas, paths[0], files=paths, stitch=stitch, notes=[note])

    def _product(self, o, target: Target, coverage: bool = True) -> Product:
        coll = _text(o["obs_collection"])
        inst = _text(o["instrument_name"])
        obs_id = _text(o["obs_id"])
        filt = filters.effective_filter(_text(o["filters"])) or _text(o["filters"])
        wl, band = filters.parse(filt, inst)
        lo, hi = _float(o["em_min"]), _float(o["em_max"])  # nm
        if wl is None and lo and hi:
            wl = (lo + hi) / 2000
        t_min = _float(o["t_min"])
        url = file_url(coll, inst, obs_id)
        mosaic = coll == "HST" and hst_family(obs_id) == "mosaic"
        scale = MOSAIC_PIXEL_SCALE if mosaic else _pixel_scale(inst, wl)
        c_ra, c_dec = _float(o["s_ra"]), _float(o["s_dec"])
        offset = (footprint.angular_sep_deg(c_ra, c_dec, target.ra, target.dec) * 60
                  if c_ra is not None and c_dec is not None else None)

        # Download estimates (S-26) for the science array only (REQ-57), as float32.
        if mosaic:  # only the rows of the box around the object, each a full skycell row
            box_px = int(self._mosaic_box_arcmin(target) * 60 / MOSAIC_PIXEL_SCALE)
            size = min(box_px, SKYCELL_WIDTH_PX) * SKYCELL_WIDTH_PX * 4
            level = "HST mosaic (cut around object)"
            width = SKYCELL_WIDTH_PX
        elif coll == "PS1":
            size, level, width = PS1_STACK_BYTES, "PS1 stack", None
        else:
            area = footprint.area_deg2(_text(o["s_region"]))
            size = int(area * (3600 / scale) ** 2 * 4) if area and scale else None
            level = "HST single-visit " + url.rsplit("_", 1)[-1][:3] if coll == "HST" else "JWST i2d"
            width = None
        return Product(
            archive=self.name, collection=coll, telescope={"PS1": "Pan-STARRS1"}.get(coll, coll), instrument=inst,
            filter=filt, obs_id=obs_id, url=url,
            wavelength_um=wl, bandwidth_um=(hi - lo) / 1000 if lo and hi else None, band_type=band,
            exptime_s=_float(o["t_exptime"]), obs_date=Time(t_min, format="mjd").isot[:10] if t_min else "",
            pixel_scale_arcsec=scale, size_bytes=size, width=width, is_mosaic=mosaic, product_level=level,
            centre_ra=c_ra, centre_dec=c_dec, offset_arcmin=offset, grid=grid_key(coll, filt, obs_id),
            thumbnail_url=_http(_text(o["jpegURL"])), science_extension=1 if coll == "PS1" else "SCI",
            coverage=(footprint.coverage([_text(o["s_region"])], target.ra, target.dec, target.size_arcmin)
                      if coverage else None),
            region=_text(o["s_region"]),
        )
