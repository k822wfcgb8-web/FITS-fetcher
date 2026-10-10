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
"""
from __future__ import annotations

import logging

import astropy.units as u
from astropy.coordinates import SkyCoord
from astropy.time import Time
from astroquery.mast import Observations

from fits_fetcher import filters, footprint
from fits_fetcher.archives.base import Archive, ArchiveError, Product, Target

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
PS1_STACK_BYTES = 68_000_000  # a whole compressed PS1 stack file (verification step 05)
DRC_INSTRUMENTS = ("ACS/WFC", "WFC3/UVIS")  # CTE-corrected products; everything else is _drz

# HST multi-visit mosaics: one skycell is about 21,258 px wide at 0.04"/px (verified on M51's skycell).
SKYCELL_WIDTH_PX = 21258
MOSAIC_PIXEL_SCALE = 0.04


def hst_family(obs_id: str) -> str:
    """'mosaic', 'single-visit' or 'classic' (REQ-58)."""
    obs_id = obs_id.lower()
    if obs_id.startswith("hst_skycell"):
        return "mosaic"
    if obs_id.startswith("hst_"):
        return "single-visit"
    return "classic"


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

    def search(self, target: Target, radius_deg: float) -> list[Product]:
        collections = [c for c in self.settings.mast_collections if c in INSTRUMENTS]
        try:
            obs = Observations.query_criteria(
                coordinates=SkyCoord(target.ra * u.deg, target.dec * u.deg), radius=radius_deg * u.deg,
                obs_collection=collections, dataproduct_type="image", calib_level=[3],
                intentType="science", dataRights="PUBLIC")
        except Exception as e:
            raise ArchiveError(f"MAST search failed: {e}") from e

        products = []
        for r in obs:
            if (_allowed(_text(r["obs_collection"]), _text(r["instrument_name"]))
                    and self._wanted_family(r)
                    and filters.effective_filter(_text(r["filters"]))
                    and footprint.contains(_text(r["s_region"]), target.ra, target.dec)):
                products.append(self._product(r, target))
        return products

    def _wanted_family(self, row) -> bool:
        if _text(row["obs_collection"]) != "HST":
            return True
        obs_id = _text(row["obs_id"]).lower()
        if "_total_" in obs_id or obs_id.endswith("_coarse-all"):
            return False
        family = hst_family(obs_id)
        return family == "single-visit" or (family == "mosaic" and self.settings.hst_show_mosaics)

    def _mosaic_box_arcmin(self, target: Target) -> float:
        """REQ-25/REQ-58: 2x the object's size, or the default when the size is unknown."""
        return 2 * target.size_arcmin if target.size_arcmin else self.settings.cutout_default_arcmin

    def _product(self, o, target: Target) -> Product:
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

        # Download estimates (S-26) for the science array only (REQ-57), as float32.
        if mosaic:  # only the rows of the box around the object, each a full skycell row
            box_px = int(self._mosaic_box_arcmin(target) * 60 / MOSAIC_PIXEL_SCALE)
            size = min(box_px, SKYCELL_WIDTH_PX) * SKYCELL_WIDTH_PX * 4
            level = "HST mosaic (cut around object)"
        elif coll == "PS1":
            size, level = PS1_STACK_BYTES, "PS1 stack"
        else:
            area = footprint.area_deg2(_text(o["s_region"]))
            size = int(area * (3600 / scale) ** 2 * 4) if area and scale else None
            level = "HST single-visit " + url.rsplit("_", 1)[-1][:3] if coll == "HST" else "JWST i2d"
        return Product(
            archive=self.name, collection=coll, telescope={"PS1": "Pan-STARRS1"}.get(coll, coll), instrument=inst,
            filter=filt, obs_id=obs_id, url=url,
            wavelength_um=wl, bandwidth_um=(hi - lo) / 1000 if lo and hi else None, band_type=band,
            exptime_s=_float(o["t_exptime"]), obs_date=Time(t_min, format="mjd").isot[:10] if t_min else "",
            pixel_scale_arcsec=scale, size_bytes=size, is_mosaic=mosaic, product_level=level,
            thumbnail_url=_http(_text(o["jpegURL"])), science_extension=1 if coll == "PS1" else "SCI",
        )
