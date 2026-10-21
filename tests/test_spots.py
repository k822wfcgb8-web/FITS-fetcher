"""Off-centre colour sets (REQ-71)."""
import numpy as np
import pytest

from conftest import make_product
from fits_fetcher import footprint, spots
from fits_fetcher.archives.base import Target

CLUSTER = Target(query="M35", matched_id="NGC 2168", ra=100.0, dec=20.0, size_arcmin=30.0)


def square(dx_arcmin: float, dy_arcmin: float, side_arcmin: float = 2.0, around: Target = CLUSTER) -> str:
    """A square footprint centred dx east, dy north of the cluster's centre."""
    h = side_arcmin / 2
    corners = [(dx_arcmin - h, dy_arcmin - h), (dx_arcmin + h, dy_arcmin - h),
               (dx_arcmin + h, dy_arcmin + h), (dx_arcmin - h, dy_arcmin + h)]
    pts = footprint._offsets(around.ra, around.dec, [(x / 60, y / 60) for x, y in corners])
    return "POLYGON " + " ".join(f"{ra} {dec}" for ra, dec in pts)


def image(filt, region, grid="HST visit 1_01 WFC3/UVIS", instrument="WFC3/UVIS", exptime=100.0, **kw):
    ra, dec = _centre(region)
    return make_product(filt, instrument, obs_id=kw.pop("obs_id", f"{grid}-{filt}"), exptime=exptime, grid=grid,
                        region=region, centre_ra=ra, centre_dec=dec, **kw)


def _centre(region):
    nums = [float(n) for n in region.split() if n != "POLYGON"]
    return float(np.mean(nums[0::2])), float(np.mean(nums[1::2]))


def test_footprint_helpers():
    x, y = footprint.tangent_arcsec([100.0], [20.1], 100.0, 20.0)
    assert x[0] == pytest.approx(0, abs=1e-6) and y[0] == pytest.approx(360, rel=1e-3)
    (ra, dec), = footprint.sky_from_tangent(x, y, 100.0, 20.0)
    assert (ra, dec) == pytest.approx((100.0, 20.1))
    # concave L-shape: the notch is outside
    ell = [np.array([[0, 0], [2, 0], [2, 1], [1, 1], [1, 2], [0, 2]], dtype=float)]
    assert footprint.inside_mask(ell, [0.5, 1.5, 1.5], [1.5, 0.5, 1.5]).tolist() == [True, True, False]
    assert footprint.compass(footprint.position_angle_deg(100, 20, 100.1, 20.1)) == "NE"
    assert footprint.compass(footprint.position_angle_deg(100, 20, 100, 19.9)) == "S"


def test_off_centre_group_on_one_grid_becomes_a_set():
    imgs = [image(f, square(0, 6)) for f in ("F555W", "F606W", "F814W")]
    [cs] = spots.build(imgs, CLUSTER, min_filters=3)
    assert [r.filter for r in cs.rows] == ["F555W", "F606W", "F814W"]
    assert cs.position["direction"] == "N" and cs.position["offset_arcmin"] == pytest.approx(6, abs=0.1)
    assert cs.position["area_arcmin2"] == pytest.approx(4, rel=0.05)
    assert cs.coverage == pytest.approx(4 / (np.pi * 15 ** 2), rel=0.05)
    assert cs.name.endswith("_6.0arcmin-N") and len(cs.grids) == 1 and len(cs.grids[0].products) == 3
    delivered = [p for r in cs.rows for p in r.products]
    assert len({p.key for p in delivered}) == 3 and all(p.spot and p.cut for p in delivered)
    assert all(p.key != i.key for p, i in zip(delivered, imgs))  # never collides with the uncut product
    assert {tuple(map(tuple, p.cut)) for p in delivered} == {tuple(map(tuple, delivered[0].cut))}  # one box


def test_shared_area_is_the_overlap():
    # Three 2' squares, each shifted 1' east: only a 0' wide strip is common to all three -> nothing;
    # shifted 0.5' they share a 1' x 2' strip.
    assert spots.build([image(f, square(6 + i, 0)) for i, f in enumerate(("F555W", "F606W", "F814W"))], CLUSTER) == []
    [cs] = spots.build([image(f, square(6 + i / 2, 0)) for i, f in enumerate(("F555W", "F606W", "F814W"))], CLUSTER)
    assert cs.position["area_arcmin2"] == pytest.approx(2, rel=0.08)
    assert cs.position["offset_arcmin"] == pytest.approx(6.5, abs=0.1)


@pytest.mark.parametrize("why, imgs, kw", [
    ("contains the centre", [image(f, square(0.5, 0.5)) for f in ("F555W", "F606W", "F814W")], {}),
    ("outside the disc", [image(f, square(0, 20)) for f in ("F555W", "F606W", "F814W")], {}),
    ("too few filters", [image(f, square(0, 6)) for f in ("F555W", "F606W")], {}),
    ("different grids", [image(f, square(0, 6), grid=f"HST visit 1_0{i} WFC3/UVIS")
                         for i, f in enumerate(("F555W", "F606W", "F814W"))], {}),
    ("no grid claim (JWST)", [image(f, square(0, 6), grid="") for f in ("F555W", "F606W", "F814W")], {}),
    ("sliver", [image(f, square(0, 6, side_arcmin=0.4)) for f in ("F555W", "F606W", "F814W")], {}),
    ("size unknown", [image(f, square(0, 6)) for f in ("F555W", "F606W", "F814W")], {"unsized": True}),
])
def test_no_set(why, imgs, kw):
    target = Target(query="x", matched_id="x", ra=CLUSTER.ra, dec=CLUSTER.dec) if kw.get("unsized") else CLUSTER
    assert spots.build(imgs, target, min_filters=3) == [], why


def test_instruments_kept_apart_unless_mixing():
    grid = "HST skycell p1"
    imgs = [image("F555W", square(0, 6), grid=grid, instrument="ACS/WFC"),
            image("F606W", square(0, 6), grid=grid, instrument="ACS/WFC"),
            image("F814W", square(0, 6), grid=grid, instrument="WFC3/UVIS")]
    assert spots.build(imgs, CLUSTER, min_filters=3) == []
    [cs] = spots.build(imgs, CLUSTER, min_filters=3, mix_instruments=True)
    assert cs.instruments == ["ACS/WFC", "WFC3/UVIS"]


def test_deeper_mosaic_replaces_the_same_area_from_one_visit():
    visit = [image(f, square(0, 6), exptime=10.0) for f in ("F555W", "F606W", "F814W")]
    mosaic = [image(f, square(0, 6, side_arcmin=3), grid="HST skycell p1", exptime=50.0, is_mosaic=True,
                    width=21258, scale=0.04) for f in ("F555W", "F606W", "F814W")]
    [cs] = spots.build(visit + mosaic, CLUSTER)
    assert cs.grids[0].grid == "HST skycell p1"
    p = cs.rows[0].products[0]
    rows = 3 * 60 / 0.04 + 2 * spots.MOSAIC_MARGIN_PX
    assert p.size_bytes == pytest.approx(rows * 21258 * 4, rel=0.05)  # only the rows of the area
    # A visit with an extra filter is not replaced: it offers something the mosaic doesn't.
    visit.append(image("F656N", square(0, 6), exptime=10.0))
    assert len(spots.build(visit + mosaic, CLUSTER)) == 2


def test_two_separate_areas_on_one_grid_are_two_sets():
    imgs = [image(f, square(0, 6)) for f in ("F555W", "F606W", "F814W")]
    imgs += [image(f, square(6, 0), obs_id=f"b-{f}") for f in ("F555W", "F606W", "F814W")]
    sets = spots.build(imgs, CLUSTER)
    assert sorted(s.position["direction"] for s in sets) == ["E", "N"]
    assert all(len(r.products) == 1 for s in sets for r in s.rows)


def rect(x0, x1, y0, y1, around: Target = CLUSTER) -> str:
    """A rectangle footprint, edges in arcmin east and north of the cluster's centre."""
    pts = footprint._offsets(around.ra, around.dec, [(x / 60, y / 60) for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))])
    return "POLYGON " + " ".join(f"{ra} {dec}" for ra, dec in pts)


@pytest.mark.parametrize("gap_arcsec, both_chips", [(1.5, True), (10, False)])
def test_a_set_split_by_a_chip_gap_keeps_both_chips(gap_arcsec, both_chips):
    # NGC 976's skycell: MAST draws each filter as two CCDs with a 1.2-1.6" gap; the lower one holds the centre.
    # The set is still offered for the upper chip, but its box takes in both (REQ-104); a wider gap doesn't.
    g = gap_arcsec / 60
    chips = rect(-1, 1, -0.5, 1) + " " + rect(-1, 1, 1 + g, 2.5)
    [cs] = spots.build([image(f, chips) for f in ("F555W", "F606W", "F814W")], CLUSTER, min_filters=3)
    decs = [dec for _, dec in cs.rows[0].products[0].cut]
    reaches = (min(decs) - CLUSTER.dec) * 60
    if both_chips:
        assert reaches == pytest.approx(-0.5, abs=0.05) and cs.position["area_arcmin2"] == pytest.approx(6, rel=0.05)
    else:
        assert reaches == pytest.approx(1 + g, abs=0.05) and cs.position["area_arcmin2"] == pytest.approx(2 * (1.5 - g), rel=0.05)


# ---------- MAST: candidates and download ----------
def test_elsewhere_offers_mosaics_even_with_the_switch_off(monkeypatch):
    from fits_fetcher.archives import mast
    from fits_fetcher.config import Settings
    from test_mast import obs_table

    near = square(0, 6)
    ra, dec = _centre(near)
    base = {"s_region": near, "s_ra": ra, "s_dec": dec}
    rows = [{**base, "obs_id": "hst_1_01_acs_wfc_f555w_j1", "filters": "F555W"},          # single-visit
            {**base, "obs_id": "hst_skycell-p1_acs_wfc_f814w_all"},                       # mosaic
            {**base, "obs_id": "jd8f17020"},                                              # classic: never
            {**base, "obs_collection": "JWST", "instrument_name": "NIRCAM/IMAGE", "filters": "F200W",
             "obs_id": "jw1-o1_t1_nircam_f200w"}]                                         # no grid claim
    calls = []
    monkeypatch.setattr(mast.Observations, "query_criteria", lambda **kw: calls.append(kw) or obs_table(rows))
    archive = mast.MastArchive(Settings(hst_show_mosaics=False))
    got = archive.elsewhere(CLUSTER)
    assert sorted(p.obs_id for p in got) == ["hst_1_01_acs_wfc_f555w_j1", "hst_skycell-p1_acs_wfc_f814w_all"]
    assert all(p.region == near and p.coverage is None for p in got)
    archive.inside(CLUSTER, 3)
    assert len(calls) == 1  # inside() reuses the same query of the disc


def test_cut_download_falls_back_to_drz_and_keeps_the_shared_box(tmp_path):
    from dataclasses import replace

    from astropy.wcs import WCS

    from fakes import DEC, RA, FakeSession, hst_like_file, wcs_header
    from fits_fetcher.archives import mast
    from fits_fetcher.config import Settings
    from fits_fetcher.processing import Options, process
    from fits_fetcher.transfer import Transfer

    data = np.arange(100 * 100, dtype=np.float32).reshape(100, 100) + 1
    obs_id = "hst_1_01_wfc3_uvis_f606w_i1"
    drc = mast.file_url("HST", "WFC3/UVIS", obs_id)
    assert drc.endswith("_drc.fits")
    corners = WCS(wcs_header(100, 100)).all_pix2world([[30, 40], [50, 40], [50, 50], [30, 50]], 0).tolist()
    p = replace(make_product("F606W", "WFC3/UVIS", obs_id=obs_id), url=drc, science_extension="SCI",
                cut=[tuple(c) for c in corners], spot="s1")
    session = FakeSession({drc.removesuffix("_drc.fits") + "_drz.fits": hst_like_file(data)})
    target = Target(query="x", matched_id="X", ra=RA, dec=DEC, size_arcmin=30.0)
    f = mast.MastArchive(Settings()).fetch(p, target, Transfer(tmp_path, session=session), 1.0, lambda d, n: None)
    assert f.url.endswith("_drz.fits") and f.box == (30, 51, 40, 51)
    r = process(f, p, target, Options(cutout=True, star_repair=False))  # "cut around the object" doesn't apply
    assert r.data.shape == (11, 21) and r.data[0, 0] == data[40, 30]
    hist = "".join(str(c) for c in r.header["HISTORY"])
    assert "_drz.fits" in hist and "Cut to the area all filters of this set share (s1): 21 x 11 px" in hist
    assert r.header["FFCUTOUT"] is False


def test_search_streams_off_centre_sets_and_they_can_be_downloaded(monkeypatch):
    from fastapi.testclient import TestClient

    from fits_fetcher.archives.base import Archive
    from fits_fetcher.config import Settings
    from fits_fetcher.web import app as webapp
    from test_web import events

    class Cluster(Archive):
        name = "GOOD"
        def search(self, target, radius_deg):
            return []
        def elsewhere(self, target):
            return [image(f, square(0, 6)) for f in ("F555W", "F606W", "F814W", "F656N")]

    monkeypatch.setattr(webapp, "ARCHIVES", {"GOOD": Cluster})
    c = TestClient(webapp.create_app(Settings()))
    params = {"ra": CLUSTER.ra, "dec": CLUSTER.dec, "archives": "GOOD", "size_arcmin": 30, "min_filters": 3}
    ev = events(c.get("/api/search", params=params).text)
    names = [e for e, _ in ev]
    assert names.index("sets") < names.index("elsewhere") < names.index("inside")
    [cs] = [d for e, d in ev if e == "elsewhere"][-1]["sets"]
    assert cs["position"]["direction"] == "N" and len(cs["rows"]) == 4
    # REQ-19 still applies: broadband only leaves 3 filters
    ev = events(c.get("/api/search", params={**params, "band_type": "broad"}).text)
    assert [len(s["rows"]) for s in [d for e, d in ev if e == "elsewhere"][-1]["sets"]] == [3]
    # the server knows the cut products, so a download request for them is accepted
    key = cs["rows"][0]["products"][0]["key"]
    r = c.post("/api/download", json={"target": {"query": "M35", "matched_id": "M35", "ra": CLUSTER.ra,
                                                 "dec": CLUSTER.dec, "size_arcmin": 30},
                                      "items": [{"key": key, "sets": [cs["name"]]}], "star_repair": True, "cutout": False})
    assert r.status_code == 200
