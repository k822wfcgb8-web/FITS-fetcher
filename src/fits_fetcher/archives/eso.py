"""ESO module: combined VISTA, VST, HAWK-I and SOFI images (REQ-90 to REQ-93), each delivered as a box around the
object.

Selection and delivery come from verification steps 02, 03 and 20 (verify/FINDINGS.md):
- Searched through ESO's ObsCore TAP table (answers in 0.2-1 s). `calib_level` isn't used: every ESO image product
  says 2, reduced tiles and stacks included. Only combined products are taken: `dataproduct_subtype` is blank for
  them and 'pawprint' for unmerged multi-chip files, which REQ-12 excludes. Only the ticked telescopes' instruments
  are searched (REQ-90), so ALMA, APEX, NGTS, SPHERE and the rest never appear. Rows with several filters in one
  file and rows not yet public are dropped; the footprint must contain the object's centre (REQ-14).
- Repeat epochs (REQ-91): VVV observed the same tiles dozens of times (M8: 80 Ks tiles). Only the deepest image
  (ESO's 5-sigma limiting magnitude, else the exposure time) of each pointing is kept, per data collection and
  filter; images whose centres are further apart than a tenth of the field (at least 1') are different pointings
  and stay, e.g. HAWK-I's four pointings around M83.
- Every image is a box centred on the object, 1.5x its size, cut by ESO's SODA cutout service on the file's own
  pixel grid with no resampling (REQ-92; CRPIX moves by whole pixels). A box past the image edge comes back clipped
  (REQ-86). No two ESO filters share a pixel grid (VHS J, Y and Ks tiles of one night differ slightly), so nothing
  gets a Grid letter (REQ-60).
- Thumbnails (REQ-93): ESO's previews are PDFs, so the CDS hips2fits service draws the box from the survey's own
  sky map where one exists (VHS, VIKING, VVV, UltraVISTA, KiDS); otherwise the row shows the placeholder until
  the image is downloaded.
- No off-centre sets or 'Also inside' list, and nothing for planets and moons (REQ-90, as for IRSA).
"""
from __future__ import annotations

import datetime as dt
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
from fits_fetcher.transfer import Progress, Transfer

log = logging.getLogger(__name__)

TAP_URL = "https://archive.eso.org/tap_obs"
SODA_URL = "https://dataportal.eso.org/dataPortal/soda/sync"
FILE_URL = "https://dataportal.eso.org/dataPortal/file/"
HIPS2FITS = "https://alasky.cds.unistra.fr/hips-image-services/hips2fits"
THUMB_PX = 200
# REQ-91: images of one data collection and filter whose centres are closer than this share of the field (and
# than 1') are repeats of one pointing.
REPEAT_SHARE = 0.1
REPEAT_MIN_ARCMIN = 1.0


@dataclass(frozen=True)
class Telescope:
    name: str           # shown on rows; the fact sheet is keyed by the setting's name (REQ-74)
    instrument: str     # ESO's instrument_name
    label: str          # instrument as shown on rows
    level: str          # product description for the details view


TELESCOPES = {
    "VISTA": Telescope("VISTA", "VIRCAM", "VIRCAM", "VISTA tile"),
    "VST": Telescope("VST", "OMEGACAM", "OmegaCAM", "VST combined image"),
    "HAWKI": Telescope("VLT", "HAWKI", "HAWK-I", "HAWK-I stack"),
    "SOFI": Telescope("NTT", "SOFI", "SOFI", "SOFI stack"),
}

# ESO filter names → the names the app uses (filters._NAMED); others are kept as ESO writes them.
FILTER_NAMES = {"u_SDSS": "u", "g_SDSS": "g", "r_SDSS": "r", "i_SDSS": "i", "z_SDSS": "z", "NB_659": "NB659"}
# Narrowband: bandwidth under this share of the central wavelength (Brγ 1.3%, NB_659 1.8%; CH4 7% is not).
NARROW_SHARE = 0.05

# REQ-93: CDS sky maps made from the survey's own images, by data collection, then filter (ESO's name). KiDS has
# colour maps only. Areas a survey doesn't cover come back blank.
HIPS = {
    "VHS": {"Y": "wfau.roe.ac.uk/P/VISTA/VHS/Y", "J": "wfau.roe.ac.uk/P/VISTA/VHS/J",
            "H": "wfau.roe.ac.uk/P/VISTA/VHS/H", "Ks": "wfau.roe.ac.uk/P/VISTA/VHS/K"},
    "VIKING": {b: f"CDS/P/VISTA/VIKING/{'K' if b == 'Ks' else b}" for b in ("Z", "Y", "J", "H", "Ks")},
    "VVV": {b: f"CDS/P/VISTA/VVV/DR4/{b}" for b in ("Z", "Y", "J")},
    "UltraVISTA": {b: f"CDS/P/ULTRAVISTA/{b}" for b in ("Y", "J", "H", "Ks", "NB118")},
    "KIDS": {"u_SDSS": "CDS/P/KiDS/DR5/color-ug", "g_SDSS": "CDS/P/KiDS/DR5/color-gri",
             "r_SDSS": "CDS/P/KiDS/DR5/color-gri", "i_SDSS": "CDS/P/KiDS/DR5/color-gri"},
}

COLUMNS = ("dp_id", "obs_collection", "instrument_name", "filter", "s_region", "s_ra", "s_dec", "s_fov",
           "s_pixel_scale", "s_xel1", "s_xel2", "em_min", "em_max", "t_min", "t_exptime", "abmaglim",
           "access_estsize", "proposal_id")


def filter_name(eso: str) -> str | None:
    """The app's name for an ESO filter; None for a file holding several filters ('g_SDSS, i_SDSS, …')."""
    eso = (eso or "").strip()
    if not eso or "," in eso or eso in ("--", "None"):
        return None
    return FILTER_NAMES.get(eso, eso)


def depth(r) -> tuple[float, float]:
    """REQ-91: how deep an image is, for choosing among repeats: limiting magnitude first, then exposure."""
    return (_float(r["abmaglim"]) or -99.0, _float(r["t_exptime"]) or 0.0)


def drop_repeats(rows: list) -> list:
    """REQ-91: the deepest image of each pointing, per data collection, instrument and filter."""
    groups: dict[tuple, list] = {}
    for r in rows:
        groups.setdefault((_text(r["obs_collection"]), _text(r["instrument_name"]), _text(r["filter"])), []).append(r)
    kept = []
    for group in groups.values():
        chosen: list = []
        for r in sorted(group, key=depth, reverse=True):
            ra, dec = _float(r["s_ra"]), _float(r["s_dec"])
            near = max(REPEAT_MIN_ARCMIN, REPEAT_SHARE * (_float(r["s_fov"]) or 0) * 60) / 60
            if ra is None or dec is None or not any(
                    footprint.angular_sep_deg(ra, dec, _float(c["s_ra"]), _float(c["s_dec"])) < near for c in chosen):
                chosen.append(r)
        kept += chosen
    return kept


def _plain(e: Exception) -> str:
    """S-33: say what went wrong without the query."""
    code = re.search(r"\b(5\d\d)\b", str(e))
    if code:
        return f"its archive search is temporarily unavailable (HTTP {code.group(1)}). Try again later."
    if isinstance(e, requests.Timeout) or "timed out" in str(e).lower():
        return "its archive search didn't answer in time. Try again later."
    return f"ESO search failed: {str(e).split(' for url:')[0]}"


def _text(v) -> str:
    s = str(v)
    return "" if s in ("--", "None", "nan") else s.strip()


def _float(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f != f else f


class EsoArchive(Archive):
    name = "ESO"

    def _telescopes(self) -> list[str]:
        return [t for t in self.settings.eso_telescopes if t in TELESCOPES]

    def _query(self, target: Target, instruments: list[str]):
        today = dt.date.today().isoformat()
        names = ", ".join(f"'{i}'" for i in instruments)
        adql = (f"SELECT {', '.join(COLUMNS)} FROM ivoa.ObsCore WHERE dataproduct_type = 'image' "
                f"AND dataproduct_subtype IS NULL AND instrument_name IN ({names}) "
                f"AND obs_release_date < '{today}' "
                f"AND CONTAINS(POINT('ICRS', {target.ra:.7f}, {target.dec:.7f}), s_region) = 1")
        try:
            service = pyvo.dal.TAPService(TAP_URL, session=TimeoutSession(self.settings.archive_timeout_s))
            return service.run_sync(adql, maxrec=20000).to_table()
        except Exception as e:
            raise ArchiveError(_plain(e)) from e

    def box_arcmin(self, target: Target) -> float:
        return footprint.stitch_box_arcmin(target.size_arcmin, self.settings.cutout_default_arcmin)

    def search(self, target: Target, radius_deg: float) -> list[Product]:
        telescopes = self._telescopes()
        if target.body or not telescopes:  # planets and moons: Hubble and JWST only (REQ-79)
            return []
        by_instrument = {TELESCOPES[t].instrument: t for t in telescopes}
        rows = [r for r in self._query(target, list(by_instrument))
                if _text(r["instrument_name"]) in by_instrument and filter_name(_text(r["filter"]))
                and footprint.contains(_text(r["s_region"]), target.ra, target.dec)]  # REQ-14, done again here
        return [self._product(r, by_instrument[_text(r["instrument_name"])], target) for r in drop_repeats(rows)]

    def _product(self, r, key: str, target: Target) -> Product:
        tel = TELESCOPES[key]
        survey = _text(r["obs_collection"])
        eso_filter = _text(r["filter"])
        filt = filter_name(eso_filter)
        lo, hi = _float(r["em_min"]), _float(r["em_max"])  # metres (ObsCore)
        wl, band = filters.parse(filt, tel.instrument)
        if wl is None and lo and hi:
            wl = (lo + hi) / 2 * 1e6
            band = "narrow" if (hi - lo) / ((lo + hi) / 2) < NARROW_SHARE else "broad"
        scale = _float(r["s_pixel_scale"]) or 0.34
        side = self.box_arcmin(target)
        box_px = math.ceil(round(side * 60 / scale, 6))
        nx, ny = _float(r["s_xel1"]), _float(r["s_xel2"])
        c_ra, c_dec = _float(r["s_ra"]), _float(r["s_dec"])
        w, h = footprint.clipped_box_px(target.ra, target.dec, box_px, c_ra, c_dec, nx, ny, scale)  # REQ-86
        # The cutout comes compressed like the file (VISTA, VST: Rice, about 1 byte per pixel; HAWK-I, SOFI:
        # plain 4-byte floats), so scale the file's bytes per pixel.
        kb = _float(r["access_estsize"])
        per_px = kb * 1024 / (nx * ny) if kb and nx and ny else 4.0
        t_min = _float(r["t_min"])
        dp_id = _text(r["dp_id"])
        region = _text(r["s_region"])
        return Product(
            archive=self.name, collection=key, telescope=tel.name, instrument=tel.label, filter=filt,
            obs_id=dp_id, url=FILE_URL + dp_id, survey=survey,
            wavelength_um=wl, bandwidth_um=(hi - lo) * 1e6 if lo and hi else None, band_type=band,
            exptime_s=_float(r["t_exptime"]), obs_date=Time(t_min, format="mjd").isot[:10] if t_min else "",
            pixel_scale_arcsec=scale, size_bytes=int(w * h * min(per_px, 4.0)), width=w, height=h,
            product_level=f"{tel.level} ({survey}"
                          + (f", depth {_float(r['abmaglim']):.1f} AB mag" if _float(r["abmaglim"]) else "")
                          + f"), {side:.1f}′ box around the object",
            thumbnail_url=self._thumbnail(survey, eso_filter, target, side),
            science_extension=0, centre_ra=c_ra, centre_dec=c_dec,
            offset_arcmin=(footprint.angular_sep_deg(c_ra, c_dec, target.ra, target.dec) * 60
                           if c_ra is not None and c_dec is not None else None),
            region=region, boxed=True,
            coverage=footprint.coverage([region], target.ra, target.dec, target.size_arcmin),
        )

    @staticmethod
    def _thumbnail(survey: str, eso_filter: str, target: Target, side_arcmin: float) -> str:
        hips = HIPS.get(survey, {}).get(eso_filter)
        if not hips:
            return ""  # the placeholder; a thumbnail is made from the image once downloaded (REQ-27)
        return HIPS2FITS + "?" + urlencode({
            "hips": hips, "ra": f"{target.ra:.6f}", "dec": f"{target.dec:.6f}", "fov": f"{side_arcmin / 60:.5f}",
            "width": THUMB_PX, "height": THUMB_PX, "projection": "TAN", "format": "jpg"})

    # ---------- download ----------
    def fetch(self, product: Product, target: Target, transfer: Transfer, box_arcmin: float,
              progress: Progress) -> Fetched:
        """REQ-92: ESO's SODA service cuts the box on the file's own grid. A CIRCLE of radius r returns the square
        of side 2r around it (checked on M83: 0.05° gave 1054 px at 0.341″). VISTA and VST cutouts are
        tile-compressed, with the image in HDU 1; HAWK-I and SOFI ones are a plain primary image."""
        from astropy.io import fits

        side = self.box_arcmin(target)
        url = SODA_URL + "?" + urlencode({"ID": f"ivo://eso.org/ID?{product.obs_id}",
                                          "CIRCLE": f"{target.ra:.7f} {target.dec:.7f} {side / 120:.7f}"})
        path = transfer.fetch(url, progress=progress, suffix=".fits")
        try:
            with fits.open(path) as hl:
                index = next((i for i, hdu in enumerate(hl) if hdu.header.get("NAXIS") == 2
                              or hdu.header.get("ZNAXIS") == 2), None)
                if index is None:
                    raise ArchiveError(f"ESO's cutout of {product.obs_id} holds no image (is the object off its "
                                       "edge?).")
                primary, header = hl[0].header.copy(), hl[index].header.copy()
        except (OSError, ValueError) as e:
            raise ArchiveError(f"ESO's cutout of {product.obs_id} isn't a readable FITS file: {e}") from e
        nx, ny = header.get("NAXIS1", 0), header.get("NAXIS2", 0)
        want = math.ceil(round(side * 60 / product.pixel_scale_arcsec, 6))
        clipped = nx < want - 2 or ny < want - 2  # SODA rounds the box to whole pixels
        note = (f"Box of {nx} x {ny} px around the object cut by ESO's cutout service from {product.obs_id} "
                f"({product.survey}), on the file's own pixel grid with no resampling.")
        return Fetched(primary, header, path, hdu=index, files=[path], box=(0, nx, 0, ny), box_clipped=clipped,
                       box_arcmin=side, notes=[note], url=url)
