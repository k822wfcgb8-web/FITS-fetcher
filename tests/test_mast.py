import pytest
from astropy.table import Table

from fits_fetcher.archives import mast
from fits_fetcher.archives.base import Target
from fits_fetcher.config import Settings

M51 = Target(query="M51", matched_id="M 51", ra=202.4696, dec=47.1953, size_arcmin=9.0)
COVERS = "POLYGON 202.37 47.10 202.57 47.10 202.57 47.30 202.37 47.30"
MISSES = "POLYGON 203.37 47.10 203.57 47.10 203.57 47.30 203.37 47.30"


def obs_table(rows):
    cols = ["obs_collection", "instrument_name", "filters", "obs_id", "s_region", "em_min", "em_max",
            "t_min", "t_exptime", "jpegURL", "s_ra", "s_dec", "target_name"]
    return Table(rows=[[r.get(c, d) for c, d in zip(cols, ["HST", "ACS/WFC", "F814W", "x", COVERS, 700.0, 900.0,
                                                            58000.0, 1000.0, "", 202.47, 47.20, "TARGET"])] for r in rows],
                 names=cols)


@pytest.fixture
def fake_mast(monkeypatch):
    def install(rows):
        monkeypatch.setattr(mast.Observations, "query_criteria", lambda **kw: obs_table(rows))
    return install


@pytest.mark.parametrize("obs_id, family", [
    ("hst_skycell-p2261x11y16_acs_wfc_f814w_all", "mosaic"),
    ("hst_14704_17_acs_wfc_f814w_jd8f17", "single-visit"),
    ("jd8f17020", "classic"),
])
def test_hst_family(obs_id, family):
    assert mast.hst_family(obs_id) == family


@pytest.mark.parametrize("coll, inst, obs_id, ending", [
    ("HST", "ACS/WFC", "hst_1_01_acs_wfc_f814w_j1", "mast:HST/product/hst_1_01_acs_wfc_f814w_j1_drc.fits"),
    ("HST", "WFC3/UVIS", "hst_1_01_wfc3_uvis_f336w_i1", "_drc.fits"),
    ("HST", "WFC3/IR", "hst_1_01_wfc3_ir_f160w_i1", "_drz.fits"),
    ("HST", "WFPC2/PC", "hst_1_01_wfpc2_pc_f814w_u1", "_drz.fits"),
    ("HST", "ACS/HRC", "hst_1_01_acs_hrc_f330w_j1", "_drz.fits"),
    ("JWST", "NIRCAM/IMAGE", "jw03435-o001_t002_nircam_clear-f430m", "mast:JWST/product/jw03435-o001_t002_nircam_clear-f430m_i2d.fits"),
    ("PS1", "GPC1", "rings.v3.skycell.2261.075.stk.r",
     "ps1images.stsci.edu/rings.v3.skycell/2261/075/rings.v3.skycell.2261.075.stk.r.unconv.fits"),
])
def test_file_url(coll, inst, obs_id, ending):
    assert mast.file_url(coll, inst, obs_id).endswith(ending)


def test_search_applies_selection_rules(fake_mast):
    fake_mast([
        {"obs_id": "hst_1_01_acs_wfc_f814w_j1"},                               # kept
        {"obs_id": "jd8f17020"},                                                # classic: dropped
        {"obs_id": "hst_1_01_acs_wfc_total_j1", "filters": "F435W;F814W"},      # white light: dropped
        {"obs_id": "hst_skycell-p1_acs_wfc_f814w_all"},                         # mosaic, switch off: dropped
        {"obs_id": "hst_1_02_acs_wfc_f435w_j1", "s_region": MISSES},           # doesn't contain centre
        {"obs_id": "hst_1_03_stis_ccd_mirvis_o1", "instrument_name": "STIS/CCD", "filters": "MIRVIS"},
        {"obs_collection": "JWST", "instrument_name": "NIRCAM/IMAGE", "filters": "F444W;F405N",
         "obs_id": "jw1-o1_t1_nircam_f405n-f444w", "em_min": 4000.0, "em_max": 4100.0},
        {"obs_collection": "PS1", "instrument_name": "GPC1", "filters": "r", "obs_id": "rings.v3.skycell.2261.075.stk.r"},
    ])
    found = mast.MastArchive(Settings()).search(M51, 0.02)
    assert sorted(p.obs_id for p in found) == [
        "hst_1_01_acs_wfc_f814w_j1", "jw1-o1_t1_nircam_f405n-f444w", "rings.v3.skycell.2261.075.stk.r"]
    jwst = next(p for p in found if p.collection == "JWST")
    assert jwst.filter == "F405N" and jwst.band_type == "narrow" and jwst.pixel_scale_arcsec == 0.063
    assert all(p.size_bytes for p in found)


@pytest.mark.parametrize("coll, filt, obs_id, grid", [
    ("HST", "F502N", "hst_17500_06_wfc3_uvis_f502n_if8506", "HST visit 17500_06 WFC3/UVIS"),
    ("HST", "F631N", "hst_17500_06_wfc3_uvis_f631n_if8506", "HST visit 17500_06 WFC3/UVIS"),
    ("HST", "F814W", "hst_skycell-p2261x11y16_acs_wfc_f814w_all", "HST skycell p2261x11y16"),
    ("PS1", "r", "rings.v3.skycell.2261.075.stk.r", "PS1 skycell 2261.075"),
    ("JWST", "F444W", "jw1-o1_t1_nircam_f444w", ""),
    ("HST", "F814W", "jd8f17020", ""),
])
def test_grid_key(coll, filt, obs_id, grid):
    assert mast.grid_key(coll, filt, obs_id) == grid


def test_image_centre_and_offset(fake_mast):
    fake_mast([{"obs_id": "hst_1_01_acs_wfc_f814w_j1", "s_ra": M51.ra, "s_dec": M51.dec + 0.05}])
    p = mast.MastArchive(Settings()).search(M51, 0.02)[0]
    assert (p.centre_ra, p.centre_dec) == (M51.ra, M51.dec + 0.05)
    assert p.offset_arcmin == pytest.approx(3.0)


def test_mosaics_when_switched_on(fake_mast):
    fake_mast([{"obs_id": "hst_skycell-p1_acs_wfc_f814w_all"},
               {"obs_id": "hst_skycell-p1_wfc3_ir_f160w_coarse-all", "instrument_name": "WFC3/IR", "filters": "F160W"}])
    found = mast.MastArchive(Settings(hst_show_mosaics=True)).search(M51, 0.02)
    assert [p.obs_id for p in found] == ["hst_skycell-p1_acs_wfc_f814w_all"]  # coarse grid dropped
    assert found[0].is_mosaic and found[0].pixel_scale_arcsec == 0.04


def test_mosaic_box_estimate_uses_object_size(fake_mast):
    fake_mast([{"obs_id": "hst_skycell-p1_acs_wfc_f814w_all"}])
    small = Target(query="x", matched_id="x", ra=M51.ra, dec=M51.dec, size_arcmin=2.0)
    p = mast.MastArchive(Settings(hst_show_mosaics=True)).search(small, 0.02)[0]
    rows = int(2 * 2.0 * 60 / 0.04)  # 2x size, in 0.04" pixels
    assert p.size_bytes == rows * mast.SKYCELL_WIDTH_PX * 4


def test_query_failure_becomes_archive_error(monkeypatch):
    def boom(**kw):
        raise ConnectionError("down")
    monkeypatch.setattr(mast.Observations, "query_criteria", boom)
    with pytest.raises(mast.ArchiveError, match="MAST search failed"):
        mast.MastArchive(Settings()).search(M51, 0.02)
