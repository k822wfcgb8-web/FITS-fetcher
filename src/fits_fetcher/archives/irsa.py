"""IRSA module: Spitzer, WISE and 2MASS pipeline images (REQ-56), each delivered as a box around the object.

Selection and delivery come from verification steps 02, 08 and 19 (verify/FINDINGS.md) and REQ-85 to REQ-88:
- Searched through IRSA's SIA service (its ObsCore table omits Spitzer), one query for every ticked collection
  (REQ-87). Only rows labelled `science` are used (the others are noise, weight and coverage maps, REQ-32), and
  only if the footprint contains the object's centre (REQ-14). `calib_level` isn't used: 2MASS co-adds say 2.
- Every image is a box centred on the object, 1.5x its size (REQ-85, the Pan-STARRS rule), on the archive's own
  pixel grid with no resampling. WISE and 2MASS files are on IRSA's IBE file service, whose cutout option
  (`?center=ra,dec&size=…`) returns that box; every band of one WISE tile came back with the same size and CRPIX
  (verification step 19), so they stack pixel-for-pixel. Spitzer mosaics live outside IBE, where the cutout option
  is ignored, so only the box's rows are fetched with range requests (like HST mosaics) and cut afterwards.
- A box running past the image edge is clipped to the image (REQ-86); coverage shows how much is missing.
- Thumbnails (REQ-27): IRSA has no preview images, so the CDS hips2fits service draws the box from the survey's
  own sky map (HiPS, made from the same atlas images and mosaics), about 6 KB and 0.5 s each.
- No off-centre sets or 'Also inside' list (REQ-88), and nothing for planets and moons (REQ-79).
"""
from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass
from urllib.parse import urlencode

import pyvo
import requests
from astropy.time import Time

from fits_fetcher import filters, footprint
from fits_fetcher.archives.base import Archive, ArchiveError, Fetched, Product, Target, TimeoutSession
from fits_fetcher.transfer import Progress, Transfer, TransferError

log = logging.getLogger(__name__)

SIA_URL = "https://irsa.ipac.caltech.edu/SIA"
HIPS2FITS = "https://alasky.cds.unistra.fr/hips-image-services/hips2fits"
THUMB_PX = 200
# Extra mosaic rows fetched above and below a Spitzer box, so star cores on its edge can still be repaired
# (REQ-38) before the box is cut; the same margin as HST mosaics.
ROW_MARGIN_PX = 64


@dataclass(frozen=True)
class Collection:
    telescope: str      # name shown on rows (REQ-87); the fact sheet is keyed by the collection
    instrument: str     # "" = take the archive's instrument name (Spitzer: IRAC or MIPS)
    pixel_scale: dict[str, float]  # arcsec per pixel, by instrument ("" for all)
    level: str          # product description for the details view
    cutout: bool        # served by IBE, which cuts the box itself
    hips: str           # CDS HiPS ID prefix for thumbnails, the band appended


COLLECTIONS = {
    "spitzer_seip": Collection("Spitzer", "", {"IRAC": 0.6, "MIPS": 2.45}, "Spitzer Enhanced Imaging Products mosaic",
                               False, "CDS/P/SPITZER/"),
    "wise_allwise": Collection("WISE", "AllWISE atlas", {"": 1.375}, "AllWISE atlas image", True, "CDS/P/allWISE/"),
    "twomass_allsky": Collection("2MASS", "2MASS atlas", {"": 1.0}, "2MASS All-Sky atlas image", True, "CDS/P/2MASS/"),
}

# Band names in the SIA results → the filter names the app uses (filters._NAMED) and the HiPS band.
BANDS = {
    "IRAC1": ("IRAC1", "IRAC1"), "IRAC2": ("IRAC2", "IRAC2"), "IRAC3": ("IRAC3", "IRAC3"), "IRAC4": ("IRAC4", "IRAC4"),
    "MIPS24": ("MIPS24", "MIPS1"),
    "W1": ("W1", "W1"), "W2": ("W2", "W2"), "W3": ("W3", "W3"), "W4": ("W4", "W4"),
    "J": ("J", "J"), "H": ("H", "H"), "K": ("Ks", "K"), "KS": ("Ks", "K"),
}


def band_of(name: str) -> tuple[str, str] | None:
    """(filter name, HiPS band) for an SIA band name such as 'IRAC1', 'W3' or 'K'; None if it isn't one we use."""
    key = re.sub(r"[^A-Za-z0-9]", "", name or "").upper()
    key = {"IRAC36": "IRAC1", "IRAC45": "IRAC2", "IRAC58": "IRAC3", "IRAC80": "IRAC4", "MIPS": "MIPS24"}.get(key, key)
    return BANDS.get(key)


def wise_tile(url: str) -> str:
    """The AllWISE tile ('coadd ID') of an atlas file: …/2029p469_ac51-w1-int-3.fits → '2029p469_ac51'."""
    m = re.search(r"/(\d{4}[pm]\d{3}_[a-z0-9]+)-w\d-int", url)
    return m.group(1) if m else ""


def twomass_tile(url: str) -> str:
    """The 2MASS atlas image a file belongs to, without its band: …/980527n/s024/image/ji0240232.fits.gz →
    '980527n-0240232' (night and hemisphere, scan and tile). J, H and Ks of one image share one pixel grid exactly
    (verification step 19: same size, CRVAL, CRPIX and rotation)."""
    m = re.search(r"/(\d{6}[ns])/s\d{3}/image/[jhk]i(\d{7})\.fits", url, re.IGNORECASE)
    return f"{m.group(1)}-{m.group(2)}".lower() if m else ""


def seip_region(url: str) -> str:
    """The Spitzer Enhanced Imaging Products region of an IRAC mosaic: …/50058000.50058000-0.IRAC.2.mosaic.fits →
    '50058000-0'. Its four IRAC channels, and its '-short' mosaics, share one pixel grid exactly (verification
    step 19); MIPS has its own, coarser grid."""
    m = re.search(r"/\d+\.(\d+-\d+)(?:-short)?\.IRAC\.\d\.mosaic\.fits", url)
    return m.group(1) if m else ""


def short_frames(url: str) -> bool:
    """REQ-89: a '-short' IRAC mosaic, built from the short frames of a high-dynamic-range observation (3.9 s
    instead of 104 s in region 50057690-0). Same pixel grid as the full-depth mosaics, so the same grid name."""
    return bool(re.search(r"-short\.IRAC\.\d\.mosaic\.fits", url))


def grid_key(collection: str, url: str) -> str:
    """REQ-60: images with the same name share one pixel grid. Only grids checked in verification step 19 are named."""
    if collection == "spitzer_seip" and seip_region(url):
        return f"Spitzer region {seip_region(url)} IRAC box"
    if collection == "wise_allwise" and wise_tile(url):
        return f"WISE tile {wise_tile(url)} box"
    if collection == "twomass_allsky" and twomass_tile(url):
        return f"2MASS image {twomass_tile(url)} box"
    return ""


def _plain(e: Exception) -> str:
    """S-33: say what went wrong without the query URL. IRSA answered 503 for most of 2026-10-12 morning."""
    code = re.search(r"\b(5\d\d|4\d\d)\b", str(e))
    if code and code.group(1) in ("502", "503", "504"):
        return f"its image search is temporarily unavailable (HTTP {code.group(1)}). Try again later."
    if isinstance(e, requests.Timeout) or "timed out" in str(e).lower():
        return "its image search didn't answer in time. Try again later."
    return f"IRSA search failed: {str(e).split(' for url:')[0]}"


def _text(v) -> str:
    s = str(v)
    return "" if s in ("--", "None", "nan") else s


def _float(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f != f else f


def _col(row, name: str):
    try:
        return row[name]
    except (KeyError, IndexError):
        return None


class IrsaArchive(Archive):
    name = "IRSA"

    def _collections(self) -> list[str]:
        return [c for c in self.settings.irsa_collections if c in COLLECTIONS]

    def _query(self, target: Target, radius_deg: float, collections: list[str]):
        try:
            service = pyvo.dal.SIA2Service(SIA_URL, session=TimeoutSession(self.settings.archive_timeout_s),
                                           check_baseurl=False)
            return service.search(pos=(target.ra, target.dec, radius_deg), collection=collections).to_table()
        except Exception as e:
            raise ArchiveError(_plain(e)) from e

    def box_arcmin(self, target: Target) -> float:
        return footprint.stitch_box_arcmin(target.size_arcmin, self.settings.cutout_default_arcmin)

    def search(self, target: Target, radius_deg: float) -> list[Product]:
        collections = self._collections()
        if target.body or not collections:  # planets and moons: Hubble and JWST only (REQ-79, REQ-88)
            return []
        out = []
        for r in self._query(target, radius_deg, collections):
            if (_text(_col(r, "dataproduct_subtype")).lower() != "science"
                    or _text(_col(r, "obs_collection")) not in collections
                    or band_of(_text(_col(r, "energy_bandpassname"))) is None
                    or not footprint.contains(_text(_col(r, "s_region")), target.ra, target.dec)):
                continue
            out.append(self._product(r, target))
        return out

    def _product(self, r, target: Target) -> Product:
        coll = _text(r["obs_collection"])
        spec = COLLECTIONS[coll]
        filt, _ = band_of(_text(r["energy_bandpassname"]))
        inst = spec.instrument or ("MIPS" if filt.startswith("MIPS") else "IRAC")
        wl, band = filters.parse(filt, inst)
        lo, hi = _float(_col(r, "em_min")), _float(_col(r, "em_max"))  # metres (ObsCore)
        scale = spec.pixel_scale.get(inst, spec.pixel_scale.get(""))
        url = _text(r["access_url"])
        side = self.box_arcmin(target)
        box_px = math.ceil(round(side * 60 / scale, 6))
        nx, ny = _float(_col(r, "s_xel1")), _float(_col(r, "s_xel2"))
        c_ra, c_dec = _float(_col(r, "s_ra")), _float(_col(r, "s_dec"))
        w, h = footprint.clipped_box_px(target.ra, target.dec, box_px, c_ra, c_dec, nx, ny, scale)  # REQ-86
        if spec.cutout:
            size = w * h * 4
        else:  # whole mosaic rows (REQ-57)
            size = (h + 2 * ROW_MARGIN_PX) * int(nx or box_px) * 4
        t_min = _float(_col(r, "t_min"))
        region = _text(_col(r, "s_region"))
        return Product(
            archive=self.name, collection=coll, telescope=spec.telescope, instrument=inst, filter=filt,
            obs_id=_text(_col(r, "obs_id")) or url.rsplit("/", 1)[-1], url=url,
            wavelength_um=wl or ((lo + hi) / 2 * 1e6 if lo and hi else None),
            bandwidth_um=(hi - lo) * 1e6 if lo and hi else None, band_type=band,
            exptime_s=_float(_col(r, "t_exptime")), obs_date=Time(t_min, format="mjd").isot[:10] if t_min else "",
            pixel_scale_arcsec=scale, size_bytes=size, width=w, height=h,
            product_level=f"{spec.level}{' (short frames only)' if short_frames(url) else ''}, "
                          f"{side:.1f}′ box around the object",
            chip="short frames" if short_frames(url) else "",
            thumbnail_url=self._thumbnail(spec, _text(r["energy_bandpassname"]), target, side),
            science_extension=0, centre_ra=c_ra, centre_dec=c_dec,
            offset_arcmin=(footprint.angular_sep_deg(c_ra, c_dec, target.ra, target.dec) * 60
                           if c_ra is not None and c_dec is not None else None),
            grid=grid_key(coll, url), region=region, boxed=True,
            coverage=footprint.coverage([region], target.ra, target.dec, target.size_arcmin),
        )

    @staticmethod
    def _thumbnail(spec: Collection, band_name: str, target: Target, side_arcmin: float) -> str:
        hips_band = band_of(band_name)[1]
        return HIPS2FITS + "?" + urlencode({
            "hips": spec.hips + hips_band, "ra": f"{target.ra:.6f}", "dec": f"{target.dec:.6f}",
            "fov": f"{side_arcmin / 60:.5f}", "width": THUMB_PX, "height": THUMB_PX, "projection": "TAN",
            "format": "jpg"})

    # ---------- download ----------
    def fetch(self, product: Product, target: Target, transfer: Transfer, box_arcmin: float,
              progress: Progress) -> Fetched:
        side = self.box_arcmin(target)
        if COLLECTIONS[product.collection].cutout:
            return self._fetch_cutout(product, target, transfer, side, progress)
        return self._fetch_rows(product, target, transfer, side, progress)

    def _fetch_cutout(self, product: Product, target: Target, transfer: Transfer, side: float,
                      progress: Progress) -> Fetched:
        """REQ-85: IBE cuts the box on the file's own grid (gzipped, a few MB). A box past the edge comes back
        clipped (REQ-86)."""
        from astropy.io import fits

        url = f"{product.url}?{urlencode({'center': f'{target.ra:.6f},{target.dec:.6f}', 'size': f'{side:.4f}arcmin'})}"
        path = transfer.fetch(url, progress=progress, suffix=".fits.gz")
        try:
            with fits.open(path) as h:
                header = h[0].header.copy()
        except (OSError, ValueError) as e:
            raise ArchiveError(f"IRSA's cutout of {product.obs_id} isn't a readable FITS file: {e}") from e
        nx, ny = header.get("NAXIS1", 0), header.get("NAXIS2", 0)
        if header.get("NAXIS") != 2 or not nx or not ny:
            raise ArchiveError(f"IRSA's cutout of {product.obs_id} holds no image (is the object off its edge?).")
        want = math.ceil(round(side * 60 / product.pixel_scale_arcsec, 6))
        clipped = nx < want - 1 or ny < want - 1  # IBE rounds the size to whole pixels
        note = (f"Box of {nx} x {ny} px around the object cut by IRSA's cutout service from {product.obs_id}, on the "
                "file's own pixel grid with no resampling.")
        return Fetched(header, header, path, hdu=0, files=[path], box=(0, nx, 0, ny), box_clipped=clipped,
                       box_arcmin=side, notes=[note], url=url)

    def _fetch_rows(self, product: Product, target: Target, transfer: Transfer, side: float,
                    progress: Progress) -> Fetched:
        """REQ-85 for Spitzer: only the rows of the box (plus a margin), each a full mosaic row, then cut."""
        try:
            loc = transfer.locate_hdu(product.url, 0)
        except TransferError as e:
            raise ArchiveError(f"Couldn't read the header of {product.obs_id}: {e}") from e
        header = loc.header.copy()
        rows, cols = header["NAXIS2"], header["NAXIS1"]
        try:
            (x0, x1, y0, y1), clipped = footprint.pixel_box(header, target.ra, target.dec, side, (rows, cols))
        except ValueError as e:
            raise ArchiveError(str(e)) from e
        r0, r1 = max(0, y0 - ROW_MARGIN_PX), min(rows, y1 + ROW_MARGIN_PX)
        row_bytes = abs(header["BITPIX"]) // 8 * cols
        path = transfer.fetch(product.url, loc.data_offset + r0 * row_bytes, (r1 - r0) * row_bytes, progress)
        header["NAXIS2"] = r1 - r0
        header["CRPIX2"] = header["CRPIX2"] - r0
        return Fetched(loc.primary, header, path, files=[path], box=(x0, x1, y0 - r0, y1 - r0), box_clipped=clipped,
                       box_arcmin=side, url=product.url,
                       notes=[f"Rows {r0 + 1}-{r1} of the {cols} x {rows} px mosaic {product.obs_id} fetched."])
