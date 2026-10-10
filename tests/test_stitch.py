"""Pan-STARRS boxes (REQ-68), coverage (REQ-69) and objects inside (REQ-70)."""
import io
import math

import numpy as np
import pytest
from astropy.io import fits
from astropy.wcs import WCS

from fakes import FakeSession
from fits_fetcher import footprint
from fits_fetcher.archives import mast
from fits_fetcher.archives.base import Fetched, Target
from fits_fetcher.config import Settings
from fits_fetcher.grouping import build_sets
from fits_fetcher.processing import Options, process, stitch
from fits_fetcher.transfer import Transfer
from test_mast import obs_table

RA, DEC = 115.445, -14.8439
M46 = Target(query="M46", matched_id="M 46", ra=RA, dec=DEC, size_arcmin=25.3)


def square(ra, dec, half_deg):
    k = half_deg / math.cos(math.radians(dec))
    return f"POLYGON {ra - k} {dec - half_deg} {ra + k} {dec - half_deg} {ra + k} {dec + half_deg} {ra - k} {dec + half_deg}"


# ---------- geometry ----------
def test_coverage_of_half_covered_disc():
    east_half = f"POLYGON {RA} {DEC - 1} {RA + 2} {DEC - 1} {RA + 2} {DEC + 1} {RA} {DEC + 1}"
    assert footprint.coverage([east_half], RA, DEC, 25.3) == pytest.approx(0.5, abs=0.05)
    assert footprint.coverage([square(RA, DEC, 1)], RA, DEC, 25.3) == 1.0
    assert footprint.coverage([east_half], RA, DEC, None) is None


def test_box_points_span_the_box():
    pts = footprint.box_points(RA, DEC, 0.5, n=5)
    decs = sorted(d for _, d in pts)
    assert len(pts) == 25 and decs[0] == pytest.approx(DEC - 0.25, abs=1e-3) and decs[-1] == pytest.approx(DEC + 0.25, abs=1e-3)


def test_unclipped_box_may_leave_the_image():
    from fakes import wcs_header
    (x0, x1, y0, y1), clipped = footprint.pixel_box(wcs_header(50, 50, ra=RA, dec=DEC), RA, DEC, 2.0, None)
    assert (x1 - x0, y1 - y0) == (120, 120) and x0 < 0 and not clipped


# ---------- MAST: choosing skycells ----------
def ps1_row(sub, ra, dec, band="r", cell="0994", half=0.2):
    return {"obs_collection": "PS1", "instrument_name": "GPC1", "filters": band,
            "obs_id": f"rings.v3.skycell.{cell}.{sub}.stk.{band}", "s_region": square(ra, dec, half), "s_ra": ra, "s_dec": dec}


@pytest.fixture
def fake_rows(monkeypatch):
    def install(rows):
        monkeypatch.setattr(mast.Observations, "query_criteria",
                            lambda **kw: obs_table([{**r} for r in rows]))
    return install


def test_ps1_box_is_stitched_from_the_skycells_it_needs(fake_rows):
    k = 0.38 / math.cos(math.radians(DEC))
    fake_rows([ps1_row("022", RA + 0.15, DEC + 0.1),           # holds the centre
               ps1_row("023", RA + 0.15 - k, DEC + 0.1),       # west neighbour, overlaps the box
               ps1_row("032", RA + 0.15, DEC - 0.3),           # south neighbour, overlaps the box
               ps1_row("099", RA + 2, DEC + 2)])               # far away: not needed
    (p,) = mast.MastArchive(Settings()).search(M46, 0.02)
    assert p.parts == ["rings.v3.skycell.0994.022.stk.r", "rings.v3.skycell.0994.023.stk.r", "rings.v3.skycell.0994.032.stk.r"]
    assert p.obs_id == "rings.v3.skycell.0994.022+023+032.stk.r"
    assert p.size_bytes == 3 * mast.PS1_STACK_BYTES and p.width == math.ceil(1.5 * 25.3 * 60 / 0.25)
    assert p.grid == "PS1 projection cell 0994 box" and p.offset_arcmin == 0
    assert 0.85 < p.coverage < 0.97  # no south-west skycell in this layout, so a corner of the disc is missing


def test_ps1_box_crossing_a_projection_cell_falls_back_to_one_skycell(fake_rows):
    k = 0.38 / math.cos(math.radians(DEC))
    fake_rows([ps1_row("022", RA + 0.15, DEC + 0.1), ps1_row("011", RA + 0.15 - k, DEC + 0.1, cell="0995")])
    (p,) = mast.MastArchive(Settings()).search(M46, 0.02)
    assert p.parts == [] and p.obs_id == "rings.v3.skycell.0994.022.stk.r" and "whole skycell" in p.product_level


def test_ps1_box_is_never_cut_again(product):
    assert Options(cutout=True).for_product(product(parts=["a"])).cutout is False


# ---------- objects inside (REQ-70) ----------
def test_inside_lists_named_groups_that_miss_the_centre(fake_rows):
    near = square(RA + 0.02, DEC + 0.1, 0.02)  # 6' north, doesn't hold the centre
    rows = [{"obs_id": f"hst_8_01_wfpc2_pc_{f.lower()}_u1", "instrument_name": "WFPC2/PC", "filters": f,
             "target_name": "NGC-2438", "s_region": near, "s_ra": RA + 0.02, "s_dec": DEC + 0.1}
            for f in ("F502N", "F656N", "F658N", "F673N")]
    rows += [{"obs_id": "hst_9_01_acs_wfc_f606w_j1", "filters": "F606W", "target_name": "SMALL", "s_region": near,
              "s_ra": RA, "s_dec": DEC + 0.1}]                                     # 1 filter: below the minimum
    rows += [{"obs_id": f"hst_7_01_acs_wfc_{f.lower()}_j1", "filters": f, "target_name": "CORE",
              "s_region": square(RA, DEC, 0.02), "s_ra": RA, "s_dec": DEC} for f in ("F435W", "F555W", "F814W")]
    fake_rows(rows)
    (g,) = mast.MastArchive(Settings()).inside(M46, min_filters=3)
    assert (g.name, g.instrument, g.filters) == ("NGC-2438", "WFPC2/PC", ["F502N", "F656N", "F658N", "F673N"])
    assert (g.ra, g.dec) == (RA + 0.02, DEC + 0.1)
    assert mast.MastArchive(Settings()).inside(Target("q", "x", RA, DEC), 3) == []  # size unknown


# ---------- set coverage ----------
def test_set_coverage_is_lowest_best_per_filter(product):
    ps = [product("F435W", coverage=0.5), product("F435W", coverage=0.9, exptime=10), product("F555W", coverage=0.7),
          product("F814W", coverage=1.0)]
    assert build_sets(ps, min_filters=3)[0].coverage == pytest.approx(0.7)
    assert build_sets([product(f) for f in ("F435W", "F555W", "F814W")], min_filters=3)[0].coverage is None


# ---------- stitching pixels ----------
A = 2.5 / math.log(10)


def ps1_skycell(value: float, crpix: tuple[float, float], boffset: float, nx=60, ny=50, hole=None) -> bytes:
    """A compressed, asinh-encoded skycell whose linear value is `value` everywhere (NaN inside `hole`)."""
    h = fits.Header()
    h.update(CTYPE1="RA---TAN", CTYPE2="DEC--TAN", CRVAL1=RA, CRVAL2=DEC, CRPIX1=crpix[0], CRPIX2=crpix[1],
             CDELT1=-0.25 / 3600, CDELT2=0.25 / 3600, PC001001=1.0, PC001002=0.0, PC002001=0.0, PC002002=1.0,
             BOFFSET=boffset, BSOFTEN=2.0, EXPTIME=600.0)
    enc = np.full((ny, nx), A * math.asinh((value - boffset) / (2 * 2.0)), dtype=np.float32)
    if hole:
        enc[hole] = np.nan
    buf = io.BytesIO()
    fits.HDUList([fits.PrimaryHDU(), fits.CompImageHDU(enc, h, compression_type="GZIP_1", quantize_level=0.0)]).writeto(buf)
    return buf.getvalue()


def test_stitch_pastes_linearised_pieces_and_prefers_the_deeper_one(tmp_path):
    left = tmp_path / "l.fits"
    right = tmp_path / "r.fits"
    left.write_bytes(ps1_skycell(100.0, (30.5, 25.5), boffset=3.0))
    right.write_bytes(ps1_skycell(200.0, (-9.5, 25.5), boffset=7.0, hole=(slice(20, 30), slice(5, 15))))
    h = fits.Header({"NAXIS": 2, "NAXIS1": 100, "NAXIS2": 50})
    data = stitch(Fetched(fits.Header(), h, left, stitch=[(left, 1, 0, 0), (right, 1, 40, 0)]))
    assert data[10, 5] == pytest.approx(100, rel=1e-4)    # only the left piece
    assert data[10, 95] == pytest.approx(200, rel=1e-4)   # only the right piece
    assert data[10, 45] == pytest.approx(100, rel=1e-4)   # overlap: deeper inside the left piece (x=45 of 60)
    assert data[10, 55] == pytest.approx(200, rel=1e-4)   # overlap: deeper inside the right piece (x=15 of 60)
    assert data[25, 50] == pytest.approx(100, rel=1e-4)   # right piece blank there: left fills it


class CutoutSession(FakeSession):
    """Also answers PS1 cutout requests like the real service: linear float32, start = centre - size // 2."""

    def get(self, url, headers=None, stream=False, timeout=None):
        if not url.startswith(mast.PS1_CUTOUT):
            return super().get(url, headers, stream, timeout)
        from urllib.parse import parse_qs, urlparse
        q = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
        with fits.open(io.BytesIO(self.files["https://ps1images.stsci.edu" + q["red"]])) as h:
            data, hdr = h[1].data.astype(np.float32), h[1].header.copy()
        from fits_fetcher.processing import linearise
        linearise(data, hdr)
        w, ht = (int(v) for v in q["size"].split(","))
        x0, y0 = int(q["x"]) - w // 2, int(q["y"]) - ht // 2
        for k in ("BOFFSET", "BSOFTEN"):
            del hdr[k]
        hdr["CRPIX1"] -= x0
        hdr["CRPIX2"] -= y0
        buf = io.BytesIO()
        fits.PrimaryHDU(data[y0:y0 + ht, x0:x0 + w], hdr).writeto(buf)
        self.files[url] = buf.getvalue()
        return super().get(url, headers, stream, timeout)


@pytest.mark.parametrize("whole_files", [False, True])
def test_fetch_and_process_ps1_box(tmp_path, monkeypatch, whole_files):
    """Two skycells 40 px apart on one lattice, each with its own encoding → one linear box, object centred."""
    t = Target(query="x", matched_id="X", ra=RA, dec=DEC, size_arcmin=0.25)  # box 0.375' = 90 px
    files = {mast.file_url("PS1", "GPC1", "rings.v3.skycell.0994.022.stk.r"): ps1_skycell(100.0, (50.5, 25.5), 3.0, nx=60),
             mast.file_url("PS1", "GPC1", "rings.v3.skycell.0994.023.stk.r"): ps1_skycell(100.0, (10.5, 25.5), 7.0, nx=100)}
    p = mast.MastArchive(Settings())._product(obs_table([{
        "obs_collection": "PS1", "instrument_name": "GPC1", "filters": "r", "obs_id": "rings.v3.skycell.0994.022.stk.r",
        "s_ra": RA, "s_dec": DEC}])[0], t)
    from dataclasses import replace
    p = replace(p, parts=["rings.v3.skycell.0994.022.stk.r", "rings.v3.skycell.0994.023.stk.r"])
    if whole_files:  # pretend the files are tiny, so fetching them whole beats cutouts
        monkeypatch.setattr(mast, "PS1_STACK_BYTES", 1)
    session = CutoutSession(files)
    f = mast.MastArchive(Settings()).fetch(p, t, Transfer(tmp_path, session=session), 1.0, lambda d, n: None)
    assert any("fitscut" in u for u, _ in session.requests) != whole_files
    assert (f.header["NAXIS1"], f.header["NAXIS2"]) == (90, 90) and "BOFFSET" not in f.header
    (ax, ay), (bx, by) = [s[2:] for s in f.stitch]
    if whole_files:
        assert bx - ax == 40 and ay == by  # the second skycell sits 40 px further right on the same lattice
    else:
        assert min(ax, ay, bx, by) >= 0   # cutouts hold only pixels inside the box
    r = process(f, p, t, Options(star_repair=False))
    assert r.data.shape == (90, 90)
    assert np.allclose(r.data[25:65, 10:80], 100, rtol=1e-4)  # inside both skycells' rows: stitched, linear
    x, y = WCS(r.header).all_world2pix([[RA, DEC]], 0)[0]
    assert abs(x - 44.5) <= 1 and abs(y - 44.5) <= 1          # object at the centre of the box


# ---------- identifying names (REQ-70) ----------
from fits_fetcher import inside  # noqa: E402
from fits_fetcher.archives.base import InsideGroup  # noqa: E402

M51 = Target(query="M51", matched_id="M 51", ra=202.4696, dec=47.1953, size_arcmin=9.0)
SIMBAD = {  # what SIMBAD answered on 2026-10-10, keyed like inside.lookup
    "sn2005cs": ("SN 2005cs", 202.4724, 47.1745), "m51": ("M  51", 202.4696, 47.1953),
    "ngc5195": ("NGC  5195", 202.4983, 47.2661), "qxpup": ("OH 231.8+04.2", 115.5706, -14.7139),
    "oh231.8+04.2": ("OH 231.8+04.2", 115.5706, -14.7139), "at2019abn": ("NAME M51 OT2019-1", 202.4266, 47.1881),
}


def g(name, inst, filts, ra, dec):
    return InsideGroup(name, "MAST", inst, filts, ra, dec)


def test_variants_and_norm():
    assert inside.search_name("NGC-2438") == "NGC 2438" and inside.search_name("OH231.8+04.2") == "OH 231.8+04.2"
    assert inside.variants("QXPUP") == ["QX PUP", "QXPUP"]
    assert inside.norm("V* QX Pup") == "qxpup" and inside.norm("NGC  5195") == "ngc5195"


def test_identify_merges_drops_and_joins(monkeypatch):
    monkeypatch.setattr(inside, "lookup", lambda names: SIMBAD)
    groups = [g("SN2005CS", "ACS/HRC", ["F250W", "F330W", "F435W"], 202.4724, 47.1745),
              g("SN-2005CS", "ACS/WFC", ["F435W", "F555W", "F814W"], 202.4724, 47.1745),
              g("SN2005CS", "ACS/HRC", ["F555W"], 202.4724, 47.1745),            # same instrument: merged
              g("M51", "WFPC2/PC", ["F439W", "F555W", "F814W"], 202.46, 47.19),  # the searched object
              g("M51-POS4", "ACS/WFC", ["F435W", "F555W", "F814W"], 202.40, 47.15),  # unknown, near nothing
              g("ANY", "WFC3/UVIS", ["F275W", "F336W", "F438W"], 202.50, 47.18),
              g("NGC5195", "WFPC2/PC", ["F439W", "F555W", "F814W"], 202.4983, 47.2661),
              g("AT2019ABN", "WFC3/UVIS", ["F438W", "F555W", "F814W"], 202.4266, 47.1881)]
    objs = inside.identify(groups, M51)
    assert [o.name for o in objs] == ["SN 2005cs", "M51 OT2019-1", "NGC 5195"]  # by distance from the centre
    sn = objs[0]
    assert [(s.instrument, s.filters) for s in sn.sets] == [
        ("ACS/HRC", ["F250W", "F330W", "F435W", "F555W"]), ("ACS/WFC", ["F435W", "F555W", "F814W"])]


def test_unknown_name_joins_known_object_at_same_position(monkeypatch):
    monkeypatch.setattr(inside, "lookup", lambda names: {k: v for k, v in SIMBAD.items() if k != "qxpup"})
    objs = inside.identify([g("OH231.8+04.2", "WFC3/IR", ["F110W", "F160W", "F164N"], 115.5706, -14.7139),
                            g("QXPUP", "WFPC2/PC", ["F656N", "F658N", "F675W"], 115.5707, -14.7140)], M46)
    assert len(objs) == 1 and {s.instrument for s in objs[0].sets} == {"WFC3/IR", "WFPC2/PC"}


def test_identify_falls_back_to_archive_names(monkeypatch):
    def down(names):
        raise ConnectionError("SIMBAD down")
    monkeypatch.setattr(inside, "lookup", down)
    objs = inside.identify([g("M51-POS4", "ACS/WFC", ["F435W", "F555W", "F814W"], 202.40, 47.15)], M51)
    assert objs[0].name == "M51-POS4" and objs[0].sets[0].instrument == "ACS/WFC"
