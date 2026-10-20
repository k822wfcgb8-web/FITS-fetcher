import io
from urllib.parse import parse_qs, unquote, urlparse

import numpy as np
import pytest
from astropy.io import fits
from astropy.table import Table
from astropy.wcs import WCS

from fakes import FakeResponse, FakeSession, wcs_header
from fits_fetcher.archives import ArchiveError, cadc
from fits_fetcher.archives.base import Target
from fits_fetcher.config import Settings
from fits_fetcher.filters import line_for
from fits_fetcher.output import write_credits
from fits_fetcher.processing import Options, process, save
from fits_fetcher.transfer import Transfer

RA, DEC = 202.4696, 47.1953  # M51
M51 = Target(query="M51", matched_id="M 51", ra=RA, dec=DEC, size_arcmin=11.2)
FILES = "https://files.example/raven"


def square(ra, dec, half):
    return (f"polygon {ra - half} {dec + half} {ra + half} {dec + half} {ra + half} {dec - half} "
            f"{ra - half} {dec - half}")


COVERS = square(RA - 0.1, DEC + 0.05, 0.26)
MISSES = square(10.0, -20.0, 0.2)


@pytest.fixture(autouse=True)
def no_registry(monkeypatch):
    monkeypatch.setattr(cadc, "services", lambda timeout: {"tap": "https://tap.example/argus", "files": FILES})


def tap_table(rows):
    default = dict(collection="CFHTMEGAPIPE", productID="MegaPipe.276.274.G.MP9401", energy_bandpassName="g.MP9401",
                   energy_bounds_lower=4.15e-7, energy_bounds_upper=5.6e-7, time_exposure=None,
                   time_bounds_lower=None, position_sampleSize=0.185768, position_dimension_naxis1=10000,
                   position_dimension_naxis2=10000, position_bounds=COVERS, position_bounds_size=0.73,
                   metrics_magLimit=26.26, uri="cadc:CFHTSG/MegaPipe.276.274.G.MP9401.fits", contentLength=400006080)
    t = Table(rows=[[r.get(c, default[c]) for c in cadc.COLUMNS] for r in rows], names=cadc.COLUMNS,
              dtype=[object] * len(cadc.COLUMNS))
    return t


@pytest.fixture
def fake_tap(monkeypatch):
    calls = []

    def install(rows):
        def query(self, target, collections):
            calls.append(collections)
            return tap_table(rows)
        monkeypatch.setattr(cadc.CadcArchive, "_query", query)
        return calls
    return install


@pytest.mark.parametrize("coll, band, pid, expected", [
    ("CFHTMEGAPIPE", "g.MP9401", "MegaPipe.276.274.G.MP9401", "g"),
    ("CFHTMEGAPIPE", "r.MP9602", "MegaPipe.276.274.R.MP9602", "r"),
    ("CFHTMEGAPIPE", "", "MegaPipe.366.205.HA.MP9603", "Ha"),
    ("CFHTMEGAPIPE", "", "MegaPipe.366.205.OIII.MP9501", "OIII"),
    ("CFHTMEGAPIPE", "gri.MP9605", "MegaPipe.366.205.GRI.MP9605", None),  # luminance filter
    ("CFHTWIRWOLF", "Ks.WC8302", "GW001.035.637+42.346.K", "Ks"),
    ("SUBARUCADC", "W-S-G", "SCLA.053.265.W-S-G+", "g"),
    ("SUBARUCADC", "W-C-RC", "SCLA.155.224.W-C-RC", "Rc"),
    ("SUBARUCADC", "N-A-L656", "SCLA.1.2.N-A-L656", "N-A-L656"),
    ("CFHTMEGAPIPE", "", "MegaPipe.1.2.X.MP0000", None),
])
def test_filter_names(coll, band, pid, expected):
    assert cadc.filter_name(coll, band, pid) == expected


@pytest.mark.parametrize("pid, expected", [
    ("MegaPipe.276.274.G.MP9401", "MegaPipe.276.274"), ("G011.035.638+42.345.G", "G011.035.638+42.345"),
    ("GW001.035.637+42.346.K", "GW001.035.637+42.346"), ("SCLA.053.265.W-S-G+", "SCLA.053.265"),
    ("SCLA_035.556+42.350.W-J-V", "SCLA_035.556+42.350"), ("NGVS+0+0.I2", "NGVS+0+0"), ("something", ""),
])
def test_tiles(pid, expected):
    assert cadc.tile("X", pid) == expected


def test_centre_handles_the_ra_wrap():
    ra, dec = cadc.centre(square(0.0, 10.0, 0.2))
    assert (abs(ra) < 1e-9 or abs(ra - 360) < 1e-9) and abs(dec - 10.0) < 1e-9
    assert cadc.centre("") == (None, None)


def test_search_applies_selection_rules(fake_tap):
    calls = fake_tap([
        {},                                                                                       # g, kept
        {"productID": "MegaPipe.276.274.G.MP9401", "uri": "cadc:CFHTSG/MegaPipe.276.274.G.MP9401.fits.gz"},  # 2nd file
        {"productID": "MegaPipe.276.274.R.MP9601", "energy_bandpassName": "r.MP9601", "metrics_magLimit": 25.03,
         "uri": "cadc:CFHTSG/MegaPipe.276.274.R.MP9601.fits", "energy_bounds_lower": 5.67e-7,
         "energy_bounds_upper": 6.89e-7},                                                         # kept: deeper r
        {"productID": "MegaPipe.276.274.R.MP9602", "energy_bandpassName": "r.MP9602", "metrics_magLimit": 24.79},
        {"productID": "MegaPipe.276.274.GRI.MP9605", "energy_bandpassName": "gri.MP9605"},       # luminance
        {"productID": "MegaPipe.1.1.I.MP9701", "energy_bandpassName": "i.MP9701", "position_bounds": MISSES},
        {"productID": "MegaPipe.276.274.HA.MP9603", "energy_bandpassName": "", "energy_bounds_lower": -0.0,
         "energy_bounds_upper": -1e-30, "uri": "cadc:CFHTSG/MegaPipe.276.274.HA.MP9603.fits"},     # kept: Hα
        {"collection": "SUBARUCADC", "productID": "SCLA.276.274.W-J-V", "energy_bandpassName": "W-J-V",
         "energy_bounds_lower": 4.87e-7, "energy_bounds_upper": 6.01e-7, "position_sampleSize": 0.2,
         "time_exposure": 1500.0, "time_bounds_lower": 52000.0, "uri": "cadc:SUBARUCADC/SCLA.276.274.W-J-V.fits"},
        {"collection": "HST", "productID": "hst_x", "uri": "cadc:HST/x.fits"},                    # a mirror
    ])
    found = cadc.CadcArchive(Settings()).search(M51, 0.02)
    assert calls == [["CFHTMEGAPIPE", "CFHTWIRWOLF", "SUBARUCADC"]]
    assert sorted(p.obs_id for p in found) == ["MegaPipe.276.274.G.MP9401", "MegaPipe.276.274.HA.MP9603",
                                               "MegaPipe.276.274.R.MP9601", "SCLA.276.274.W-J-V"]
    g = next(p for p in found if p.filter == "g")
    assert (g.archive, g.collection, g.telescope, g.instrument, g.survey) == ("CADC", "CFHT", "CFHT", "MegaCam",
                                                                               "CFHTMEGAPIPE")
    assert g.url == FILES + "/files/cadc:CFHTSG/MegaPipe.276.274.G.MP9401.fits" and g.boxed
    assert g.grid == "CFHTMEGAPIPE tile MegaPipe.276.274 box" and g.wavelength_um == 0.48 and g.band_type == "broad"
    assert (g.width, g.height) == (5426, 5426) and g.size_bytes == 5426 * 5426 * 4  # 1.5 x 11.2' at 0.1858"
    assert "MegaPipe stack (CFHTMEGAPIPE, depth 26.3 AB mag)" in g.product_level and g.coverage > 0.99
    assert g.thumbnail_url.startswith("/api/preview?key=CADC%3ACFHT%3AMegaPipe.276.274.G.MP9401%3Ag&ra=202.469600")
    ha = next(p for p in found if p.filter == "Ha")
    assert ha.band_type == "narrow" and ha.wavelength_um == 0.659 and line_for(ha.wavelength_um, filter_name="Ha") == "Hα"
    v = next(p for p in found if p.filter == "V")
    assert (v.telescope, v.instrument) == ("Subaru", "Suprime-Cam") and abs(v.wavelength_um - 0.544) < 1e-9
    assert v.obs_date == "2001-04-01" and v.exptime_s == 1500.0 and v.grid == "SUBARUCADC tile SCLA.276.274 box"


def test_repeats_keep_the_deepest_of_each_pointing(fake_tap):
    """REQ-96: tiles of one pointing and filter become one; an old 1.6° tile elsewhere stays."""
    fake_tap([{"productID": f"MegaPipe.276.274.G.v{i}", "metrics_magLimit": 25 + i / 10} for i in range(3)]
             + [{"productID": "G014.202.473+46.721.G", "position_bounds": square(RA + 0.3, DEC - 0.3, 0.8),
                 "position_bounds_size": 1.6, "metrics_magLimit": 26.9}])
    found = {p.obs_id for p in cadc.CadcArchive(Settings()).search(M51, 0.02)}
    assert found == {"MegaPipe.276.274.G.v2", "G014.202.473+46.721.G"}


def test_only_ticked_telescopes_never_mirrors_and_no_planets(fake_tap):
    calls = fake_tap([{}])
    assert cadc.CadcArchive(Settings(cadc_telescopes=["SUBARU", "ALMA"])).search(M51, 0.02) == []
    assert calls == [["SUBARUCADC"]]  # the MegaPipe row belongs to a telescope that wasn't ticked
    s = Settings(cadc_excluded_collections=["HST", "SUBARUCADC"], cadc_telescopes=["SUBARU"])
    assert cadc.CadcArchive(s).search(M51, 0.02) == [] and len(calls) == 1  # everything ticked is excluded
    saturn = Target(query="saturn", matched_id="Saturn", ra=0, dec=0, body="Saturn")
    assert cadc.CadcArchive(Settings()).search(saturn, 0.02) == [] and len(calls) == 1


def test_query_asks_for_public_stacks_without_mirrors(monkeypatch):
    seen = {}

    class Service:
        def __init__(self, url, session=None):
            seen["url"], seen["timeout"] = url, session.timeout

        def run_sync(self, adql, maxrec=None):
            seen["adql"] = adql
            return type("R", (), {"to_table": lambda self: tap_table([])})()
    monkeypatch.setattr(cadc.pyvo.dal, "TAPService", Service)
    assert cadc.CadcArchive(Settings(archive_timeout_s=42)).search(M51, 0.02) == []
    q = seen["adql"]
    assert seen["url"] == "https://tap.example/argus" and seen["timeout"] == 42
    assert "o.collection IN ('CFHTMEGAPIPE', 'CFHTWIRWOLF', 'SUBARUCADC')" in q
    assert "NOT IN ('HST', 'HSTHLA', 'JWST', 'TESS'" in q and "p.calibrationLevel = 3" in q
    assert "a.productType = 'science'" in q and "p.dataRelease <=" in q and f"{RA:.7f}" in q


@pytest.mark.parametrize("error, message", [
    (OSError("503 Server Error: Service Unavailable for url: https://x/argus/sync"), r"temporarily unavailable \(HTTP 503\)"),
    (__import__("requests").ConnectTimeout("connect timed out"), "didn't answer in time"),
    (__import__("requests").ConnectionError("Max retries exceeded"), "couldn't be reached from this network"),
])
def test_query_failure_becomes_archive_error(monkeypatch, error, message):
    class Down:
        def __init__(self, *a, **kw):
            pass

        def run_sync(self, *a, **kw):
            raise error
    monkeypatch.setattr(cadc.pyvo.dal, "TAPService", Down)
    with pytest.raises(ArchiveError, match=message):
        cadc.CadcArchive(Settings()).search(M51, 0.02)


# ---------- registry (REQ-99) ----------
class Answer:
    def __init__(self, text="", fail=None):
        self.text, self.fail = text, fail

    def raise_for_status(self):
        if self.fail:
            raise self.fail


def test_registry_is_read_once_and_falls_back(monkeypatch):
    monkeypatch.undo()  # the real services(), not the fixture's
    import requests
    monkeypatch.setattr(cadc, "_registry", {})
    asked = []
    caps = ("# comment\nivo://cadc.nrc.ca/argus = https://new.example/argus/capabilities\n"
            "ivo://cadc.nrc.ca/global/raven = https://west.example/raven/capabilities\n")
    monkeypatch.setattr(cadc.requests, "get", lambda url, timeout: asked.append(url) or Answer(caps))
    assert cadc.services(5) == {"tap": "https://new.example/argus", "files": "https://west.example/raven"}
    assert cadc.services(5)["tap"] == "https://new.example/argus" and len(asked) == 1  # cached
    monkeypatch.setattr(cadc, "_registry", {})
    monkeypatch.setattr(cadc.requests, "get", lambda url, timeout: Answer(fail=requests.HTTPError("503")))
    assert cadc.services(5) == {k: url for k, (_, url) in cadc.SERVICES.items()}
    assert cadc._registry == {}  # a failed read isn't kept: the registry is tried again next time


# ---------- downloads (REQ-97) ----------
class FileService(FakeSession):
    """Answers like CADC's file service: CIRCLE cuts the square around it on the file's own grid, clipped at the
    edge; SUB returns a pixel range, with an optional step."""

    def __init__(self, files):
        super().__init__({})
        self.images = files

    def _cut(self, url):
        base, query = url.split("?", 1)
        data, hdr = self.images[base]
        q = {k: v[0] for k, v in parse_qs(query).items()}
        if "CIRCLE" in q:
            ra, dec, r = (float(v) for v in unquote(q["CIRCLE"]).split())
            x, y = WCS(hdr).all_world2pix([[ra, dec]], 0)[0]
            n = round(2 * r * 3600 / abs(hdr["CD2_2"] * 3600))
            x0, y0 = max(0, round(x) - n // 2), max(0, round(y) - n // 2)
            x1, y1 = min(data.shape[1], round(x) - n // 2 + n), min(data.shape[0], round(y) - n // 2 + n)
            step = 1
        else:
            (xa, xb, *xs), (ya, yb, *ys) = (part.split(":") for part in q["SUB"].removeprefix("[0][")
                                            .removesuffix("]").split(","))
            x0, x1, y0, y1, step = int(xa) - 1, int(xb), int(ya) - 1, int(yb), int((xs or ["1"])[0])
        hdr = hdr.copy()
        hdr["CRPIX1"] -= x0
        hdr["CRPIX2"] -= y0
        buf = io.BytesIO()
        fits.PrimaryHDU(data[y0:y1:step, x0:x1:step].astype(">f4"), hdr).writeto(buf)
        return buf.getvalue()

    def get(self, url, headers=None, stream=False, timeout=None, params=None):
        if params:
            url += "?" + "&".join(f"{k}={v}" for k, v in params.items())
        if "?" in url and url not in self.files:
            self.files[url] = self._cut(url)
        if url not in self.files and url in self.images:
            data, hdr = self.images[url]
            buf = io.BytesIO()
            fits.PrimaryHDU(data.astype(">f4"), hdr).writeto(buf)
            self.files[url] = buf.getvalue()
        return super().get(url, headers, stream, timeout)


def tile_header(n, scale):
    h = wcs_header(n, n, scale, RA, DEC)
    h["CRPIX1"] += 37
    h["CRPIX2"] -= 21
    h["PHOTZP"], h["FILTER"], h["EXPTIME"] = 30.0, "G.MP9401", 3110.756
    return h


def products(target, rows):
    a = cadc.CadcArchive(Settings())
    out = []
    for r in tap_table(rows):
        d = {c: r[c] for c in cadc.COLUMNS}
        d["_filter"] = cadc.filter_name(d["collection"], d["energy_bandpassName"], d["productID"])
        d["_centre"] = cadc.centre(d["position_bounds"])
        out.append(a._product(d, "CFHT", target))
    return out


def test_filters_get_the_same_box_on_their_shared_grid(tmp_path):
    t = Target(query="x", matched_id="X", ra=RA, dec=DEC, size_arcmin=0.5)  # 0.75' box = 242 px at 0.1858"
    rng = np.random.default_rng(4)
    rows = [{}, {"productID": "MegaPipe.276.274.R.MP9601", "energy_bandpassName": "r.MP9601",
                 "uri": "cadc:CFHTSG/MegaPipe.276.274.R.MP9601.fits"}]
    ps = products(t, rows)
    images = {p.url: (rng.normal(100, 1, (600, 600)), tile_header(600, 0.185768)) for p in ps}
    session = FileService(images)
    outs = []
    for p in ps:
        f = cadc.CadcArchive(Settings()).fetch(p, t, Transfer(tmp_path, session=session), 2.0, lambda d, n: None)
        assert f.hdu == 0 and not f.box_clipped and "CIRCLE=202.4696000%20" in f.url
        assert "cut by CADC's file service" in f.notes[0] and "(CFHTMEGAPIPE)" in f.notes[0]
        outs.append(process(f, p, t, Options(star_repair=False, cutout=True, box_arcmin=2.0).for_product(p)))
    assert [r.data.shape for r in outs] == [(242, 242), (242, 242)]
    assert outs[0].header["CRPIX1"] == outs[1].header["CRPIX1"]  # pixel-aligned (REQ-60)
    h = outs[0].header
    assert h["FFSURVEY"] == "CFHTMEGAPIPE" and h["FFCOLL"] == "CFHT" and h["PHOTZP"] == 30.0
    data, hdr = images[ps[0].url]
    ox, oy = hdr["CRPIX1"] - h["CRPIX1"], hdr["CRPIX2"] - h["CRPIX2"]
    assert ox == int(ox) and oy == int(oy)  # moved by whole pixels: no resampling
    assert np.allclose(outs[0].data, data[int(oy):int(oy) + 242, int(ox):int(ox) + 242], atol=1e-4)


def test_box_past_the_image_edge_is_clipped(tmp_path):
    t = Target(query="x", matched_id="X", ra=RA, dec=DEC, size_arcmin=3.0)  # 4.5' box, 1.9' image
    p = products(t, [{}])[0]
    session = FileService({p.url: (np.full((600, 600), 5.0), tile_header(600, 0.185768))})
    f = cadc.CadcArchive(Settings()).fetch(p, t, Transfer(tmp_path, session=session), 2.0, lambda d, n: None)
    assert f.box_clipped
    assert any("ran past the image edge" in w for w in process(f, p, t, Options(star_repair=False).for_product(p)).warnings)


def test_preview_is_a_thinned_cutout_of_the_box(monkeypatch):
    t = Target(query="x", matched_id="X", ra=RA, dec=DEC, size_arcmin=1.0)  # 1.5' box = 485 px → every 3rd
    p = products(t, [{}])[0]
    data = np.arange(1200 * 1200, dtype=np.float64).reshape(1200, 1200)
    session = FileService({p.url: (data, tile_header(1200, 0.185768))})
    monkeypatch.setattr(cadc.requests, "get", session.get)
    img = cadc.CadcArchive(Settings()).preview(p, RA, DEC, 1.5)
    assert img.shape == (162, 162)
    url, rng = session.requests[0]
    assert url == p.url and rng == f"bytes=0-{cadc.HEADER_BYTES - 1}"  # only the header of the 1200² file
    assert ":3," in session.requests[1][0] and session.requests[1][0].endswith(":3]")
    monkeypatch.setattr(cadc.requests, "get", lambda *a, **kw: FakeResponse(b"", 404, {}))
    with pytest.raises(ArchiveError, match="no preview of MegaPipe"):
        cadc.CadcArchive(Settings()).preview(p, RA, DEC, 1.5)


def test_credits_name_cfht_megapipe_and_cadc(tmp_path):
    t = Target(query="x", matched_id="X", ra=RA, dec=DEC, size_arcmin=0.5)
    p = products(t, [{}])[0]
    session = FileService({p.url: (np.full((600, 600), 5.0), tile_header(600, 0.185768))})
    f = cadc.CadcArchive(Settings()).fetch(p, t, Transfer(tmp_path, session=session), 2.0, lambda d, n: None)
    save(process(f, p, t, Options(star_repair=False).for_product(p)), tmp_path / "X" / "set" / "g.fits")
    text = " ".join(write_credits(tmp_path / "X").read_text().split())
    assert "CFHT MegaCam (MegaPipe stacks, CADC)" in text and "MegaPrime/MegaCam" in text
    assert "Gwyn 2008" in text and "Canadian Astronomy Data Centre" in text


def test_every_telescope_has_a_fact_sheet():
    from fits_fetcher import telescopes
    for key in Settings().cadc_telescopes:
        sheet = telescopes.TELESCOPES[key]
        assert sheet["name"] == cadc.TELESCOPES[key].name and sheet["artifacts"] and sheet["link_label"]


def test_preview_endpoint_serves_only_known_products(monkeypatch):
    from fastapi.testclient import TestClient

    from fits_fetcher.web import app as webapp
    p = products(M51, [{}])[0]
    monkeypatch.setattr(cadc.CadcArchive, "search", lambda self, target, r: [p])
    monkeypatch.setattr(cadc.CadcArchive, "preview", lambda self, prod, ra, dec, side: np.ones((4, 4)))
    monkeypatch.setattr(webapp, "ARCHIVES", {"CADC": cadc.CadcArchive})
    c = TestClient(webapp.create_app(Settings()))
    assert c.get(p.thumbnail_url).status_code == 404  # not found by a search yet
    c.get("/api/search", params={"ra": RA, "dec": DEC, "archives": "CADC"})
    r = c.get(p.thumbnail_url)
    assert r.status_code == 200 and r.content.startswith(b"\x89PNG")
    info = c.get("/api/info").json()
    assert info["archive_telescopes"] == {"CADC": ["CFHT", "SUBARU"]} and info["planned"] == []
