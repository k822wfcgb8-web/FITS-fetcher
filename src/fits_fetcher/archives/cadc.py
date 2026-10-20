"""CADC module: CFHT MegaCam and WIRCam stacks and Subaru Suprime-Cam stacks (REQ-21, REQ-35, REQ-95 to REQ-99),
each delivered as a box around the object.

Selection and delivery come from verification steps 02, 03, 21, 22 and 23 (verify/FINDINGS.md):
- Only collections CADC holds itself (REQ-21): stacked images from MegaPipe (CFHTMEGAPIPE, MegaCam), WIRWOLF
  (CFHTWIRWOLF, WIRCam) and CADC's Suprime-Cam stacks (SUBARUCADC, calibration level 3 only; level 2 is single
  exposures, which REQ-12 excludes). Mirrors of other archives (HST, JWST, TESS, Euclid, IRIS) are in the
  `cadc_excluded_collections` setting and are never queried (REQ-35). Telescope tick boxes: CFHT and Subaru (REQ-95).
- Searched through CADC's CAOM2 tables on its TAP service (ObsCore lacks filters, exposure and pixel size): level 3
  public images whose footprint contains the object's centre (REQ-14), one science file each. MegaCam's wide 'gri'
  filter (a luminance filter, not a colour) is dropped. MegaPipe's Hα and [OIII] planes have no filter name, so it
  is read from the product ID.
- Repeats (REQ-96, the ESO rule REQ-91): per collection and filter only the deepest image of each pointing is kept
  (CADC's limiting magnitude, else exposure). MegaPipe's two r filters (MP9601, MP9602) count as one filter.
- Every image is a box centred on the object, 1.5x its size, cut by CADC's file service (CIRCLE) on the file's own
  pixel grid with no resampling (REQ-97; CRPIX moves by whole pixels). All filters of one tile share one pixel
  grid (same size, CRVAL, CRPIX and CD in every filter, step 23), so they get a Grid letter (REQ-60).
- Thumbnails (REQ-98): CDS has sky maps for 0.4% of CFHT's sky and CADC's previews show a whole tile, so the app
  draws its own from a thinned cutout of the box (every n-th pixel, about 200 x 200 px, 170 KB) on request.
- Service addresses come from CADC's registry (REQ-99), read once per session, so a moved service is followed; if
  the registry can't be read the last known addresses are used and the log says so.
- No off-centre sets or 'Also inside' list, and nothing for planets and moons (REQ-95, as for ESO and IRSA).
"""
from __future__ import annotations

import io
import logging
import math
import re
import threading
from dataclasses import dataclass
from urllib.parse import quote, urlencode

import numpy as np
import pyvo
import requests
from astropy.io import fits
from astropy.time import Time

from fits_fetcher import filters, footprint
from fits_fetcher.archives.base import Archive, ArchiveError, Fetched, Product, Target, TimeoutSession
from fits_fetcher.transfer import Progress, Transfer

log = logging.getLogger(__name__)

REGISTRY_URL = "https://ws.cadc-ccda.hia-iha.nrc-cnrc.gc.ca/reg/resource-caps"
# Registry IDs of the services used, with the addresses the registry gave on 2026-10-15 (verification step 22).
SERVICES = {
    "tap": ("ivo://cadc.nrc.ca/argus", "https://ws.cadc-ccda.hia-iha.nrc-cnrc.gc.ca/argus"),
    "files": ("ivo://cadc.nrc.ca/global/raven", "https://cadc-west-01.canfar.net/raven"),
}
THUMB_PX = 200
THUMB_MAX_BYTES = 2_000_000   # a thinned cutout is ~170 KB; never pull a whole file by accident
HEADER_BYTES = 10 * 2880
REPEAT_SHARE = 0.1            # REQ-96: as ESO (REQ-91)
REPEAT_MIN_ARCMIN = 1.0
NARROW_SHARE = 0.05


@dataclass(frozen=True)
class Telescope:
    name: str                       # shown on rows; the fact sheet is keyed by the setting's name (REQ-74)
    collections: dict[str, tuple[str, str]]  # CADC collection → (instrument shown on rows, product description)


TELESCOPES = {
    "CFHT": Telescope("CFHT", {"CFHTMEGAPIPE": ("MegaCam", "MegaPipe stack"),
                               "CFHTWIRWOLF": ("WIRCam", "WIRWOLF stack")}),
    "SUBARU": Telescope("Subaru", {"SUBARUCADC": ("Suprime-Cam", "CADC Suprime-Cam stack")}),
}

# Suprime-Cam filter names → the names the app uses; MegaCam and WIRCam names are taken before the '.'.
SUPRIME = {"W-J-B": "B", "W-J-V": "V", "W-C-RC": "Rc", "W-C-IC": "Ic", "W-S-G": "g", "W-S-R": "r", "W-S-I": "i",
           "W-S-Z": "z"}
# MegaPipe narrowband planes without a filter name or passband in CAOM2: (name, centre µm, width µm). Hα from CFHT's
# MegaCam filter list (Ha.MP9603); [OIII] from the passband CAOM2 gives the same filter in other planes.
NAMED_BY_PRODUCT = {"HA": ("Ha", 0.6590, 0.0104), "OIII": ("OIII", 0.5010, 0.0100)}
DROPPED = {"gri"}  # MegaCam's wide gri filter (0.40-0.81 µm): a luminance filter, not a colour channel

COLUMNS = ("collection", "productID", "energy_bandpassName", "energy_bounds_lower", "energy_bounds_upper",
           "time_exposure", "time_bounds_lower", "position_sampleSize", "position_dimension_naxis1",
           "position_dimension_naxis2", "position_bounds", "position_bounds_size", "metrics_magLimit", "uri",
           "contentLength")

_registry: dict[str, str] = {}
_registry_lock = threading.Lock()


def services(timeout: float) -> dict[str, str]:
    """REQ-99: base URLs of the TAP and file services from CADC's registry, read once per session."""
    with _registry_lock:
        if _registry:
            return dict(_registry)
        found = {}
        try:
            r = requests.get(REGISTRY_URL, timeout=timeout)
            r.raise_for_status()
            caps = dict(line.split("=", 1) for line in r.text.splitlines() if "=" in line and not line.startswith("#"))
            caps = {k.strip(): v.strip() for k, v in caps.items()}
            for key, (ivo, _) in SERVICES.items():
                if caps.get(ivo, "").endswith("/capabilities"):
                    found[key] = caps[ivo].removesuffix("/capabilities")
        except (requests.RequestException, ValueError) as e:
            log.warning("CADC registry unreadable (%s); using the last known service addresses", e)
            return {k: url for k, (_, url) in SERVICES.items()}  # not cached: try the registry again next time
        for key, (ivo, url) in SERVICES.items():
            if key not in found:
                log.warning("CADC registry has no %s; using %s", ivo, url)
                found[key] = url
        _registry.update(found)
        return dict(found)


def filter_name(collection: str, bandpass: str, product_id: str) -> str | None:
    """The app's name for a CADC filter: 'g.MP9401' → 'g', 'Ks.WC8302' → 'Ks', 'W-S-G' → 'g', blank → read from the
    product ID ('MegaPipe.366.205.HA.MP9603' → 'Ha'); None for a filter that isn't a colour (gri) or unknown."""
    band = (bandpass or "").strip()
    if collection == "SUBARUCADC":
        name = SUPRIME.get(band.rstrip("+"), band)
    else:
        name = band.split(".")[0]
    if not name:
        parts = product_id.upper().split(".")
        name = next((NAMED_BY_PRODUCT[p][0] for p in parts if p in NAMED_BY_PRODUCT), "")
    return None if not name or name in DROPPED else name


def tile(collection: str, product_id: str) -> str:
    """REQ-60: the tile a product belongs to; its filters share one pixel grid (verification step 23).
    'MegaPipe.276.274.G.MP9401' → 'MegaPipe.276.274'; 'G011.035.638+42.345.G' → 'G011.035.638+42.345';
    'GW001.035.637+42.346.K' → 'GW001.035.637+42.346'; 'NGVS+0+0.I2' → 'NGVS+0+0'; 'SCLA.053.265.W-S-G+' →
    'SCLA.053.265'."""
    patterns = (r"^(MegaPipe\.\d+\.\d+)\.", r"^(NGVS[+-]\d+[+-]\d+)\.", r"^(GW?\d{3}\.\d{3}\.\d{3}[+-]\d{2}\.\d{3})\.", r"^(SCLA[._].+?)\.[WN]-")
    for p in patterns:
        m = re.match(p, product_id)
        if m:
            return m.group(1)
    return ""


def centre(region: str) -> tuple[float | None, float | None]:
    """The middle of a footprint polygon's corners (tiles are small, so plain means do; RA wrap handled)."""
    pts = next((nums for kind, nums in footprint.shapes(region) if kind == "POLYGON" and len(nums) >= 6), None)
    if not pts:
        return None, None
    ra0 = pts[0]
    ras = [((r - ra0 + 180) % 360 - 180) for r in pts[0::2]]
    return (ra0 + sum(ras) / len(ras)) % 360, sum(pts[1::2]) / len(pts[1::2])


def depth(r) -> tuple[float, float]:
    return (_float(r["metrics_magLimit"]) or -99.0, _float(r["time_exposure"]) or 0.0)


def drop_repeats(rows: list) -> list:
    """REQ-96: the deepest image of each pointing, per collection and filter."""
    groups: dict[tuple, list] = {}
    for r in rows:
        groups.setdefault((_text(r["collection"]), r["_filter"]), []).append(r)
    kept = []
    for group in groups.values():
        chosen: list = []
        for r in sorted(group, key=depth, reverse=True):
            ra, dec = r["_centre"]
            near = max(REPEAT_MIN_ARCMIN, REPEAT_SHARE * (_float(r["position_bounds_size"]) or 0) * 60) / 60
            if ra is None or not any(c["_centre"][0] is not None and footprint.angular_sep_deg(
                    ra, dec, *c["_centre"]) < near for c in chosen):
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
    if isinstance(e, requests.ConnectionError):
        return "its archive couldn't be reached from this network. Try again later."
    return f"CADC search failed: {str(e).split(' for url:')[0]}"


def _text(v) -> str:
    s = str(v)
    return "" if s in ("--", "None", "nan") else s.strip()


def _float(v) -> float | None:
    if v is np.ma.masked:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f != f else f


class CadcArchive(Archive):
    name = "CADC"

    def _telescopes(self) -> list[str]:
        return [t for t in self.settings.cadc_telescopes if t in TELESCOPES]

    def _collections(self, telescopes: list[str]) -> dict[str, str]:
        """CADC collection → telescope key, never one on the exclusion list (REQ-35)."""
        excluded = {c.upper() for c in self.settings.cadc_excluded_collections}
        return {c: t for t in telescopes for c in TELESCOPES[t].collections if c.upper() not in excluded}

    def _query(self, target: Target, collections: list[str]):
        names = ", ".join(f"'{c}'" for c in collections)
        excluded = ", ".join(f"'{c}'" for c in self.settings.cadc_excluded_collections) or "''"
        now = Time.now().isot[:19]
        adql = (f"SELECT o.collection, p.productID, p.energy_bandpassName, p.energy_bounds_lower, "
                f"p.energy_bounds_upper, p.time_exposure, p.time_bounds_lower, p.position_sampleSize, "
                f"p.position_dimension_naxis1, p.position_dimension_naxis2, p.position_bounds, "
                f"p.position_bounds_size, p.metrics_magLimit, a.uri, a.contentLength "
                f"FROM caom2.Plane p JOIN caom2.Observation o ON p.obsID = o.obsID "
                f"JOIN caom2.Artifact a ON a.planeID = p.planeID "
                f"WHERE o.collection IN ({names}) AND o.collection NOT IN ({excluded}) "
                f"AND p.dataProductType = 'image' AND p.calibrationLevel = 3 AND a.productType = 'science' "
                f"AND p.dataRelease <= '{now}' "
                f"AND CONTAINS(POINT('ICRS', {target.ra:.7f}, {target.dec:.7f}), p.position_bounds) = 1")
        try:
            session = TimeoutSession(self.settings.archive_timeout_s)
            service = pyvo.dal.TAPService(services(self.settings.archive_timeout_s)["tap"], session=session)
            return service.run_sync(adql, maxrec=20000).to_table()
        except Exception as e:
            raise ArchiveError(_plain(e)) from e

    def box_arcmin(self, target: Target) -> float:
        return footprint.stitch_box_arcmin(target.size_arcmin, self.settings.cutout_default_arcmin)

    def search(self, target: Target, radius_deg: float) -> list[Product]:
        telescopes = self._telescopes()
        if target.body or not telescopes:  # planets and moons: Hubble and JWST only (REQ-79)
            return []
        collections = self._collections(telescopes)
        if not collections:
            return []
        rows, seen = [], set()
        for r in self._query(target, list(collections)):
            coll, pid, uri = _text(r["collection"]), _text(r["productID"]), _text(r["uri"])
            filt = filter_name(coll, _text(r["energy_bandpassName"]), pid)
            region = _text(r["position_bounds"])
            if (coll not in collections or not filt or (coll, pid) in seen or not uri.endswith((".fits", ".fits.fz"))
                    or not footprint.contains(region, target.ra, target.dec)):  # REQ-14, done again here
                continue
            seen.add((coll, pid))  # one science file per plane
            rows.append({**{c: r[c] for c in COLUMNS}, "_filter": filt, "_centre": centre(region)})
        return [self._product(r, collections[_text(r["collection"])], target) for r in drop_repeats(rows)]

    def _product(self, r, key: str, target: Target) -> Product:
        tel = TELESCOPES[key]
        coll, pid = _text(r["collection"]), _text(r["productID"])
        inst, level = tel.collections[coll]
        filt = r["_filter"]
        lo, hi = _float(r["energy_bounds_lower"]), _float(r["energy_bounds_upper"])  # metres
        if not (lo and hi and 0 < lo < hi):  # MegaPipe's Hα planes say -0.0 (verification step 23)
            lo = hi = None
        wl, band = filters.parse(filt, inst)
        width = (hi - lo) * 1e6 if lo and hi else None
        if filt in ("Ha", "OIII") and lo is None:
            _, wl, width = next(v for v in NAMED_BY_PRODUCT.values() if v[0] == filt)
        elif lo and hi and (wl is None or (hi - lo) / ((lo + hi) / 2) < NARROW_SHARE):
            wl = (lo + hi) / 2 * 1e6
        if wl and width:
            band = "narrow" if width / wl < NARROW_SHARE else "broad"
        scale = round(_float(r["position_sampleSize"]) or 0.186, 4)  # CAOM2 gives 0.185766207876
        side = self.box_arcmin(target)
        box_px = math.ceil(round(side * 60 / scale, 6))
        c_ra, c_dec = r["_centre"]
        w, h = footprint.clipped_box_px(target.ra, target.dec, box_px, c_ra, c_dec,
                                        _float(r["position_dimension_naxis1"]), _float(r["position_dimension_naxis2"]),
                                        scale)  # REQ-86
        t_min = _float(r["time_bounds_lower"])
        mag = _float(r["metrics_magLimit"])
        region = _text(r["position_bounds"])
        grid = tile(coll, pid)
        p = Product(
            archive=self.name, collection=key, telescope=tel.name, instrument=inst, filter=filt, obs_id=pid,
            url=services(self.settings.archive_timeout_s)["files"] + "/files/" + _text(r["uri"]), survey=coll,
            wavelength_um=wl, bandwidth_um=width, band_type=band, exptime_s=_float(r["time_exposure"]),
            obs_date=Time(t_min, format="mjd").isot[:10] if t_min else "",
            pixel_scale_arcsec=scale, size_bytes=w * h * 4, width=w, height=h,  # 32-bit floats, uncompressed
            product_level=f"{level} ({coll}" + (f", depth {mag:.1f} AB mag" if mag and mag < 32 else "")
                          + f"), {side:.1f}′ box around the object",
            science_extension=0, centre_ra=c_ra, centre_dec=c_dec,
            offset_arcmin=(footprint.angular_sep_deg(c_ra, c_dec, target.ra, target.dec) * 60
                           if c_ra is not None else None),
            grid=f"{coll} tile {grid} box" if grid else "", region=region, boxed=True,
            coverage=footprint.coverage([region], target.ra, target.dec, target.size_arcmin),
        )
        p.thumbnail_url = "/api/preview?" + urlencode({"key": p.key, "ra": f"{target.ra:.6f}",
                                                       "dec": f"{target.dec:.6f}", "side": f"{side:.4f}"})
        return p

    # ---------- thumbnails (REQ-98) ----------
    def preview(self, product: Product, ra: float, dec: float, side_arcmin: float) -> np.ndarray:
        """A thinned cutout of the box: the file's header (one range request) gives the pixel box, then CADC's file
        service returns every n-th pixel of it (`SUB=[0][x0:x1:n,y0:y1:n]`), about 200 x 200 px."""
        timeout = (30, self.settings.archive_timeout_s)
        try:
            r = requests.get(product.url, headers={"Range": f"bytes=0-{HEADER_BYTES - 1}"}, timeout=timeout)
            r.raise_for_status()
            text = r.content[:HEADER_BYTES].decode("ascii", "replace")
            end = next((i for i in range(0, len(text) - 79, 80) if text[i:i + 8] == "END     "), None)
            if end is None:
                raise ArchiveError(f"no FITS header in the first {HEADER_BYTES} bytes")
            header = fits.Header.fromstring(text[:end + 80])
            (x0, x1, y0, y1), _ = footprint.pixel_box(header, ra, dec, side_arcmin,
                                                      (header["NAXIS2"], header["NAXIS1"]))
            step = max(1, math.ceil(max(x1 - x0, y1 - y0) / THUMB_PX))
            body = b""
            with requests.get(product.url, params={"SUB": f"[0][{x0 + 1}:{x1}:{step},{y0 + 1}:{y1}:{step}]"},
                              stream=True, timeout=timeout) as r:
                r.raise_for_status()
                for chunk in r.iter_content(65536):
                    body += chunk
                    if len(body) > THUMB_MAX_BYTES:
                        raise ArchiveError("the thinned cutout was larger than expected")
            with fits.open(io.BytesIO(body)) as hl:
                return np.array(hl[0].data, dtype=np.float32)
        except (requests.RequestException, OSError, ValueError, KeyError) as e:
            raise ArchiveError(f"no preview of {product.obs_id}: {e}") from e

    # ---------- download ----------
    def fetch(self, product: Product, target: Target, transfer: Transfer, box_arcmin: float,
              progress: Progress) -> Fetched:
        """REQ-97: CADC's file service cuts the box on the file's own grid. A CIRCLE of radius r returns the square
        of side 2r around it (checked on M51: 0.01° gave 389 px at 0.186″), redirected to whichever storage site
        holds the file."""
        side = self.box_arcmin(target)
        url = product.url + "?" + urlencode({"CIRCLE": f"{target.ra:.7f} {target.dec:.7f} {side / 120:.7f}"},
                                            quote_via=quote)
        path = transfer.fetch(url, progress=progress, suffix=".fits")
        try:
            with fits.open(path) as hl:
                index = next((i for i, hdu in enumerate(hl) if hdu.header.get("NAXIS") == 2
                              or hdu.header.get("ZNAXIS") == 2), None)
                if index is None:
                    raise ArchiveError(f"CADC's cutout of {product.obs_id} holds no image (is the object off its "
                                       "edge?).")
                primary, header = hl[0].header.copy(), hl[index].header.copy()
        except (OSError, ValueError) as e:
            raise ArchiveError(f"CADC's cutout of {product.obs_id} isn't a readable FITS file: {e}") from e
        nx, ny = header.get("NAXIS1", header.get("ZNAXIS1", 0)), header.get("NAXIS2", header.get("ZNAXIS2", 0))
        want = math.ceil(round(side * 60 / product.pixel_scale_arcsec, 6))
        clipped = nx < want - 2 or ny < want - 2  # the service rounds the box to whole pixels
        note = (f"Box of {nx} x {ny} px around the object cut by CADC's file service from {product.obs_id} "
                f"({product.survey}), on the file's own pixel grid with no resampling.")
        return Fetched(primary, header, path, hdu=index, files=[path], box=(0, nx, 0, ny), box_clipped=clipped,
                       box_arcmin=side, notes=[note], url=url)
