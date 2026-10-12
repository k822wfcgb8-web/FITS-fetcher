import io
import math
from urllib.parse import parse_qs, urlparse

import numpy as np
import pytest
from astropy.io import fits
from astropy.table import Table
from astropy.wcs import WCS

from fakes import FakeSession, wcs_header
from fits_fetcher import footprint
from fits_fetcher.archives import ArchiveError, eso
from fits_fetcher.archives.base import Target
from fits_fetcher.config import Settings
from fits_fetcher.output import write_credits
from fits_fetcher.processing import Options, process, save
from fits_fetcher.transfer import Transfer

RA, DEC = 204.25383, -29.86576  # M83
M83 = Target(query="M83", matched_id="M 83", ra=RA, dec=DEC, size_arcmin=12.9)
# ESO writes its frame as 'J2000', which mustn't be read as a coordinate.
COVERS = f"POLYGON J2000 {RA + 0.6} {DEC + 0.7} {RA + 0.6} {DEC - 0.7} {RA - 0.6} {DEC - 0.7} {RA - 0.6} {DEC + 0.7}"
MISSES = "POLYGON J2000 10.0 -20.0 10.5 -20.0 10.5 -20.5 10.0 -20.5"


def tap_table(rows):
    default = dict(dp_id="ADP.2016-10-06T13:12:54.463", obs_collection="VHS", instrument_name="VIRCAM", filter="J",
                   s_region=COVERS, s_ra=203.95, s_dec=-29.9089, s_fov=1.914, s_pixel_scale=0.341,
                   s_xel1=12767, s_xel2=15652, em_min=1.166e-6, em_max=1.339e-6, t_min=57088.28, t_exptime=60.0,
                   abmaglim=20.9, access_estsize=159322, proposal_id="179.A-2010(K)")
    return Table(rows=[[r.get(c, default[c]) for c in eso.COLUMNS] for r in rows], names=eso.COLUMNS)


@pytest.fixture
def fake_tap(monkeypatch):
    calls = []

    def install(rows):
        def query(self, target, instruments):
            calls.append(instruments)
            return tap_table(rows)
        monkeypatch.setattr(eso.EsoArchive, "_query", query)
        return calls
    return install


def test_frame_names_are_not_coordinates():
    assert footprint.shapes(MISSES) == [("POLYGON", [10.0, -20.0, 10.5, -20.0, 10.5, -20.5, 10.0, -20.5])]
    assert footprint.contains(COVERS, RA, DEC) and not footprint.contains(MISSES, RA, DEC)


@pytest.mark.parametrize("name, expected", [
    ("Ks", "Ks"), ("g_SDSS", "g"), ("NB_659", "NB659"), ("BrG", "BrG"), ("g_SDSS, i_SDSS, r_SDSS", None), ("", None),
])
def test_filter_names(name, expected):
    assert eso.filter_name(name) == expected


def test_search_applies_selection_rules(fake_tap):
    calls = fake_tap([
        {},                                                                               # VHS J tile, kept
        {"dp_id": "ks", "filter": "Ks", "em_min": 1.992e-6, "em_max": 2.301e-6},          # kept
        {"dp_id": "far", "filter": "Y", "s_region": MISSES},                              # misses the centre
        {"dp_id": "multi", "filter": "g_SDSS, i_SDSS, r_SDSS, u_SDSS, z_SDSS"},           # several filters in one
        {"dp_id": "sphere", "instrument_name": "SPHERE", "filter": "H"},                  # not a ticked instrument
        {"dp_id": "brg", "obs_collection": "HAWKI", "instrument_name": "HAWKI", "filter": "BrG",
         "em_min": 2.150e-6, "em_max": 2.179e-6, "s_pixel_scale": 0.106, "s_xel1": 4500, "s_xel2": 4500,
         "s_ra": RA - 0.05, "s_dec": DEC + 0.05, "s_fov": 0.12, "access_estsize": 88000, "abmaglim": None},
    ])
    found = eso.EsoArchive(Settings()).search(M83, 0.02)
    assert calls == [["VIRCAM", "OMEGACAM", "HAWKI", "SOFI"]]
    assert sorted(p.obs_id for p in found) == ["ADP.2016-10-06T13:12:54.463", "brg", "ks"]
    j = next(p for p in found if p.filter == "J")
    assert (j.archive, j.collection, j.telescope, j.instrument, j.survey) == ("ESO", "VISTA", "VISTA", "VIRCAM", "VHS")
    assert j.url == eso.FILE_URL + j.obs_id and j.boxed and j.grid == "" and j.wavelength_um == 1.25
    # 1.5 x 12.9' box at 0.341"/px = 3405 px, inside the tile; the file's 0.82 bytes per pixel
    assert (j.width, j.height) == (3405, 3405)
    assert j.size_bytes == int(3405 * 3405 * 159322 * 1024 / (12767 * 15652))
    assert "VHS, depth 20.9 AB mag" in j.product_level and "19.4′ box" in j.product_level
    assert "wfau.roe.ac.uk%2FP%2FVISTA%2FVHS%2FJ" in j.thumbnail_url and j.coverage > 0.99
    assert j.obs_date == "2015-03-07"
    brg = next(p for p in found if p.filter == "BrG")
    assert (brg.telescope, brg.instrument, brg.band_type) == ("VLT", "HAWK-I", "narrow")
    assert abs(brg.wavelength_um - 2.1645) < 1e-6 and brg.thumbnail_url == ""  # no sky map: placeholder
    assert brg.width < 9126 and brg.size_bytes == brg.width * brg.height * 4  # clipped at the 8' field, 4 B/px
    assert "depth" not in brg.product_level


def test_repeat_epochs_keep_the_deepest_of_each_pointing(fake_tap):
    """REQ-91: VVV's many Ks epochs of one tile become one; HAWK-I's other pointings and VVVX's tile stay."""
    vvv = [{"dp_id": f"vvv{i}", "obs_collection": "VVV", "filter": "Ks", "abmaglim": 18.0 + i / 10,
            "s_ra": RA + i * 1e-4} for i in range(8)]
    hawki = [{"dp_id": f"h{i}", "obs_collection": "HAWKI", "instrument_name": "HAWKI", "filter": "Ks", "s_fov": 0.12,
              "s_ra": RA + dx, "s_dec": DEC + dy, "abmaglim": 21.0, "t_exptime": t}
             for i, (dx, dy, t) in enumerate([(0.05, 0.05, 720), (-0.05, 0.05, 720), (-0.05, 0.05, 1440)])]
    fake_tap(vvv + hawki + [{"dp_id": "vvvx", "obs_collection": "VVVX", "filter": "Ks"}])
    found = {p.obs_id for p in eso.EsoArchive(Settings()).search(M83, 0.02)}
    assert found == {"vvv7", "h0", "h2", "vvvx"}  # h1 repeats h2's pointing with half the exposure


def test_only_ticked_telescopes_and_no_planets(fake_tap):
    calls = fake_tap([{}])
    assert eso.EsoArchive(Settings(eso_telescopes=["HAWKI", "ALMA"])).search(M83, 0.02) == []
    assert calls == [["HAWKI"]]  # the VIRCAM row belongs to a telescope that wasn't ticked
    saturn = Target(query="saturn", matched_id="Saturn", ra=0, dec=0, body="Saturn")
    assert eso.EsoArchive(Settings()).search(saturn, 0.02) == [] and len(calls) == 1
    assert eso.EsoArchive(Settings(eso_telescopes=[])).search(M83, 0.02) == [] and len(calls) == 1


def test_query_failure_becomes_archive_error(monkeypatch):
    class Down:
        def __init__(self, *a, **kw):
            pass

        def run_sync(self, *a, **kw):
            raise OSError("503 Server Error: Service Unavailable for url: https://archive.eso.org/tap_obs/sync")
    monkeypatch.setattr(eso.pyvo.dal, "TAPService", Down)
    with pytest.raises(ArchiveError, match=r"^its archive search is temporarily unavailable \(HTTP 503\)"):
        eso.EsoArchive(Settings()).search(M83, 0.02)


def test_query_asks_for_public_combined_images_only(monkeypatch):
    seen = {}

    class Service:
        def __init__(self, url, session=None):
            seen["url"], seen["timeout"] = url, session.timeout

        def run_sync(self, adql, maxrec=None):
            seen["adql"] = adql
            return type("R", (), {"to_table": lambda self: tap_table([])})()
    monkeypatch.setattr(eso.pyvo.dal, "TAPService", Service)
    assert eso.EsoArchive(Settings(archive_timeout_s=42)).search(M83, 0.02) == []
    q = seen["adql"]
    assert seen["url"] == eso.TAP_URL and seen["timeout"] == 42
    assert "dataproduct_subtype IS NULL" in q and "obs_release_date <" in q  # no pawprints (REQ-12), public only
    assert "instrument_name IN ('VIRCAM', 'OMEGACAM', 'HAWKI', 'SOFI')" in q and f"{RA:.7f}" in q


# ---------- downloads ----------
class SodaSession(FakeSession):
    """Answers SODA cutout requests like ESO's service: the square around CIRCLE on the file's own grid, clipped at
    the image edge; tile-compressed in HDU 1 for VISTA tiles, a plain primary image otherwise."""

    def __init__(self, files, compressed: bool):
        super().__init__(files)
        self.compressed = compressed

    def get(self, url, headers=None, stream=False, timeout=None):
        if url.startswith(eso.SODA_URL) and url not in self.files:
            q = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
            data, hdr = self.files[q["ID"].split("?", 1)[1]]
            ra, dec, r = (float(v) for v in q["CIRCLE"].split())
            x, y = WCS(hdr).all_world2pix([[ra, dec]], 0)[0]
            n = round(2 * r * 3600 / abs(hdr["CD2_2"] * 3600))
            x0, y0 = max(0, round(x) - n // 2), max(0, round(y) - n // 2)
            x1, y1 = min(data.shape[1], round(x) - n // 2 + n), min(data.shape[0], round(y) - n // 2 + n)
            hdr = hdr.copy()
            hdr["CRPIX1"] -= x0
            hdr["CRPIX2"] -= y0
            cut = data[y0:y1, x0:x1]
            buf = io.BytesIO()
            if self.compressed:
                fits.HDUList([fits.PrimaryHDU(), fits.CompImageHDU(cut.astype(np.float32), hdr)]).writeto(buf)
            else:
                fits.PrimaryHDU(cut.astype(">f4"), hdr).writeto(buf)
            self.files[url] = buf.getvalue()
        return super().get(url, headers, stream, timeout)


def tile_header(n: int, scale: float) -> fits.Header:
    h = wcs_header(n, n, scale, RA, DEC)
    h["CRPIX1"] += 37  # the tile's centre isn't the object
    h["CRPIX2"] -= 21
    h["PROG_ID"], h["PHOTZP"], h["BUNIT"] = "179.A-2010(K)", 26.6, "ADU"
    return h


def products(target, rows):
    return [eso.EsoArchive(Settings())._product(r, "VISTA", target) for r in tap_table(rows)]


@pytest.mark.parametrize("compressed", [True, False])
def test_filters_get_the_box_on_their_own_grid(tmp_path, compressed):
    t = Target(query="x", matched_id="X", ra=RA, dec=DEC, size_arcmin=0.5)  # box 0.75' = 132 px at 0.341"
    rng = np.random.default_rng(4)
    files = {f: (rng.normal(100, 1, (500, 500)), tile_header(500, 0.341)) for f in ("idJ", "idKs")}
    session = SodaSession(files, compressed)
    outs = []
    for p in products(t, [{"dp_id": "idJ", "s_ra": RA, "s_dec": DEC}, {"dp_id": "idKs", "filter": "Ks"}]):
        f = eso.EsoArchive(Settings()).fetch(p, t, Transfer(tmp_path, session=session), 2.0, lambda d, n: None)
        assert f.hdu == (1 if compressed else 0) and not f.box_clipped
        assert "cut by ESO's cutout service" in f.notes[0] and "(VHS)" in f.notes[0]
        assert "CIRCLE=" in f.url and "ivo%3A%2F%2Feso.org%2FID%3F" in f.url
        outs.append(process(f, p, t, Options(star_repair=False, cutout=True, box_arcmin=2.0).for_product(p)))
    assert [r.data.shape for r in outs] == [(132, 132), (132, 132)]
    x, y = WCS(outs[0].header).all_world2pix([[RA, DEC]], 0)[0]
    assert abs(x - 65.5) <= 1 and abs(y - 65.5) <= 1
    h = outs[0].header
    assert h["FFSURVEY"] == "VHS" and h["FFCOLL"] == "VISTA" and h["PROG_ID"] == "179.A-2010(K)"
    assert h["PHOTZP"] == 26.6 and h["FFCUTOUT"] is False and not outs[0].warnings
    # The original pixels, moved by whole pixels (no resampling): the offset is the change in CRPIX.
    data, hdr = files["idJ"]
    ox, oy = hdr["CRPIX1"] - h["CRPIX1"], hdr["CRPIX2"] - h["CRPIX2"]
    assert ox == int(ox) and oy == int(oy)
    tol = 0.1 if compressed else 1e-4  # tile compression quantises floats
    assert np.allclose(outs[0].data, data[int(oy):int(oy) + 132, int(ox):int(ox) + 132], atol=tol)


def test_box_past_the_image_edge_is_clipped(tmp_path):
    t = Target(query="x", matched_id="X", ra=RA, dec=DEC, size_arcmin=5.0)  # 7.5' box, 2.8' image
    files = {"idJ": (np.full((500, 500), 5.0), tile_header(500, 0.341))}
    p = products(t, [{"dp_id": "idJ"}])[0]
    f = eso.EsoArchive(Settings()).fetch(p, t, Transfer(tmp_path, session=SodaSession(files, False)), 2.0,
                                         lambda d, n: None)
    assert f.box_clipped
    r = process(f, p, t, Options(star_repair=False).for_product(p))
    assert any("ran past the image edge" in w for w in r.warnings)


def test_cutout_without_an_image_is_an_archive_error(tmp_path):
    t = Target(query="x", matched_id="X", ra=RA, dec=DEC, size_arcmin=1.0)
    p = products(t, [{"dp_id": "empty"}])[0]
    buf = io.BytesIO()
    fits.PrimaryHDU().writeto(buf)

    class Empty(FakeSession):
        def get(self, url, headers=None, stream=False, timeout=None):
            self.files[url] = buf.getvalue()
            return super().get(url, headers, stream, timeout)
    with pytest.raises(ArchiveError, match="holds no image"):
        eso.EsoArchive(Settings()).fetch(p, t, Transfer(tmp_path, session=Empty({})), 2.0, lambda d, n: None)


def test_credits_give_programme_and_collection_doi(tmp_path):
    t = Target(query="x", matched_id="X", ra=RA, dec=DEC, size_arcmin=0.5)
    files = {"idJ": (np.full((500, 500), 5.0), tile_header(500, 0.341))}
    p = products(t, [{"dp_id": "idJ"}])[0]
    f = eso.EsoArchive(Settings()).fetch(p, t, Transfer(tmp_path, session=SodaSession(files, False)), 2.0,
                                         lambda d, n: None)
    save(process(f, p, t, Options(star_repair=False).for_product(p)), tmp_path / "X" / "set" / "J.fits")
    text = " ".join(write_credits(tmp_path / "X").read_text().split())
    assert "ESO VHS" in text and "ESO programme(s) 179.A-2010(K)" in text
    assert "https://doi.org/10.18727/archive/57" in text


def test_every_telescope_has_a_fact_sheet():
    from fits_fetcher import telescopes
    for key in Settings().eso_telescopes:
        sheet = telescopes.TELESCOPES[key]
        assert sheet["name"] == eso.TELESCOPES[key].name and sheet["artifacts"] and "ESO" in sheet["link_label"]
    assert math.isclose(eso.NARROW_SHARE, 0.05)
