import numpy as np
from astropy.io import fits

from fits_fetcher.archives.base import Target
from fits_fetcher.output import file_name, object_folder, output_paths, safe, thumbnail_png, write_credits


def t(mid, **kw):
    return Target(query="q", matched_id=mid, ra=202.47, dec=47.195, **kw)


def test_object_folder_names():
    assert object_folder(t("M 51")) == "M51"
    assert object_folder(t("NGC 5194")) == "NGC5194"
    assert object_folder(t("NAME Orion Bar")) == "Orion_Bar"
    assert object_folder(t("(coordinates entered)")) == "RA202.4700_Dec+47.1950"


def test_file_and_set_paths(product, tmp_path):
    p = product("F814W", instrument="ACS/WFC", obs_id="hst_10452_05_acs_wfc_f814w_j97c05")
    assert file_name(p) == "F814W_ACS-WFC_hst_10452_05_acs_wfc_f814w_j97c05.fits"
    paths = output_paths(tmp_path, t("M 51"), p, ["ACS-WFC_F435W-F555W-F814W", "ACS-WFC+GPC1_F814W-r"])
    assert [x.relative_to(tmp_path).parts[:2] for x in paths] == [
        ("M51", "ACS-WFC_F435W-F555W-F814W"), ("M51", "ACS-WFC+GPC1_F814W-r")]


def test_long_names_are_shortened():
    name = safe("A" * 300)
    assert len(name) <= 120 and name != safe("A" * 299)


def _saved(path, coll, obsid, **cards):
    h = fits.Header({"FFCOLL": coll, "FFARCH": "MAST", "FFOBSID": obsid, **cards})
    path.parent.mkdir(parents=True, exist_ok=True)
    fits.PrimaryHDU(np.zeros((4, 4), np.float32), h).writeto(path)


def test_credits_file(tmp_path):
    obj = tmp_path / "M51"
    _saved(obj / "set1" / "a.fits", "HST", "hst_10452_05_acs", PROPOSID=10452)
    _saved(obj / "set1" / "b.fits", "HST", "hst_12762_05_wfc3")
    _saved(obj / "set2" / "c.fits", "JWST", "jw03435-o008_t006_miri_f770w")
    _saved(obj / "set3" / "d.fits", "PS1", "rings.v3.skycell.2261.075.stk.r")
    text = write_credits(obj).read_text()
    assert "NAS 5-26555" in text and "program(s) 10452, 12762" in text
    assert "NAS 5-03127" in text and "program(s) 3435" in text
    assert "Gordon and Betty Moore Foundation" in text
    assert "set1/a.fits" in text


def test_thumbnail_is_png(tmp_path):
    p = tmp_path / "x.fits"
    fits.PrimaryHDU(np.random.default_rng(0).normal(size=(500, 300)).astype(np.float32)).writeto(p)
    png = thumbnail_png(p)
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    w, h = int.from_bytes(png[16:20], "big"), int.from_bytes(png[20:24], "big")
    assert max(w, h) <= 128 and h > w
