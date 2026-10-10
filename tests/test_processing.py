import math
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest
from astropy.io import fits
from astropy.wcs import WCS

from fakes import DEC, RA, wcs_header
from fits_fetcher import footprint
from fits_fetcher.archives.base import Fetched, Target
from fits_fetcher.processing import (Options, ProcessingError, check_compatible, existing_matches, linearise,
                                     nan_to_zero, process, read_science, repair_star_cores, save)

TARGET = Target(query="M51", matched_id="M 51", ra=RA, dec=DEC, size_arcmin=1.0)


def raw_fetched(tmp_path: Path, data: np.ndarray, **kw) -> Fetched:
    path = tmp_path / "sci.bin"
    data.astype(">f4").tofile(path)
    h = wcs_header(data.shape[1], data.shape[0])
    h["NAXIS"], h["NAXIS1"], h["NAXIS2"], h["BITPIX"] = 2, data.shape[1], data.shape[0], -32
    h["BUNIT"] = "ELECTRONS/S"
    primary = fits.Header({"TELESCOP": "HST", "PROPOSID": 10452})
    return Fetched(primary, h, path, files=[path], **kw)


# ---------- reading and linearising ----------
def test_read_raw_big_endian_bytes(tmp_path):
    data = np.arange(12, dtype=np.float32).reshape(3, 4)
    got = read_science(raw_fetched(tmp_path, data))
    assert got.dtype == np.float32 and got.dtype.byteorder in ("=", "<") and np.array_equal(got, data)


def test_read_scaled_integers(tmp_path):
    path = tmp_path / "i.bin"
    np.array([[0, 100]], dtype=">i2").tofile(path)
    h = fits.Header({"NAXIS": 2, "NAXIS1": 2, "NAXIS2": 1, "BITPIX": 16, "BSCALE": 0.5, "BZERO": 10.0})
    assert read_science(Fetched(fits.Header(), h, path)).tolist() == [[10.0, 60.0]]


def test_ps1_linearisation_formula():
    h = fits.Header({"BOFFSET": 2.0, "BSOFTEN": 3.0})
    x = np.array([0.0, 1.0, -2.0], dtype=np.float32)
    linearise(x, h)
    a = 2.5 / math.log(10)
    assert np.allclose(x, [2 + 3 * 2 * math.sinh(v / a) for v in (0.0, 1.0, -2.0)])
    assert linearise(np.zeros(2), fits.Header()) is None  # other products untouched


# ---------- star-core repair (REQ-37–40) ----------
def test_enclosed_holes_filled_from_rim_symmetrically():
    data = np.full((20, 20), 5.0, dtype=np.float32)
    data[8:11, 8:11] = np.nan            # 3x3 NaN core
    data[9, 9] = 0.0                     # zero counts as a hole too
    data[8:11, 7] = 2.0                  # dimmer left rim
    data[8:11, 11] = 2.0                 # dimmer right rim, same as the left
    r = repair_star_cores(data, 100)
    assert (r.regions, r.pixels, r.bright) == (1, 9, 0)
    assert np.isfinite(data).all() and (data != 0).all()
    assert data[9, 8] == pytest.approx(data[9, 10])  # left and right fill the same: no raster bias


def test_edge_touching_and_large_regions_are_left_alone():
    data = np.full((30, 30), 1.0, dtype=np.float32)
    data[0:3, 10:13] = np.nan        # touches the edge (off-detector border)
    data[10:22, 10:22] = 0.0         # 144 px, over the limit (chip gap / blank area)
    data[25, 25] = np.nan            # small enclosed hole
    r = repair_star_cores(data, 100)
    assert (r.regions, r.pixels) == (1, 1)
    assert np.isnan(data[0:3, 10:13]).all() and (data[10:22, 10:22] == 0).all() and data[25, 25] == 1.0


def _sky_with_hole(rim_value: float, size: int = 40):
    """Noisy sky (sigma 1) with a size x size blank hole whose 3-px surroundings are set to `rim_value`."""
    data = np.random.default_rng(3).normal(10, 1, (200, 200)).astype(np.float32)
    data[77:77 + size + 6, 77:77 + size + 6] = rim_value
    data[80:80 + size, 80:80 + size] = 0.0
    return data


def test_large_hole_next_to_bright_star_is_filled():
    """REQ-67: a 1,600 px hole over the 100 px limit, edged by starlight 100 sigma above the sky."""
    data = _sky_with_hole(rim_value=110.0)
    r = repair_star_cores(data, 100, 5000)
    assert (r.regions, r.pixels, r.bright) == (1, 1600, 1)
    assert data[100, 100] == pytest.approx(110.0)


def test_large_hole_in_empty_sky_stays_blank():
    data = _sky_with_hole(rim_value=12.0)  # 2 sigma: an ordinary blank block
    r = repair_star_cores(data, 100, 5000)
    assert r.regions == 0 and (data[80:120, 80:120] == 0).all()


def test_bright_hole_over_second_limit_stays_blank():
    data = _sky_with_hole(rim_value=110.0)
    assert repair_star_cores(data, 100, 1000).regions == 0


def test_nan_to_zero_counts():
    data = np.array([1.0, np.nan, np.inf, 2.0], dtype=np.float32)
    assert nan_to_zero(data) == 2 and data.tolist() == [1.0, 0.0, 0.0, 2.0]


# ---------- cutout (REQ-25, REQ-58) ----------
def test_pixel_box_is_centred_and_integer():
    h = wcs_header(101, 81)  # object at the reference pixel: zero-based (50, 40)
    (x0, x1, y0, y1), clipped = footprint.pixel_box(h, RA, DEC, 21 / 60, (81, 101))  # 21" at 1"/px
    assert (x0, x1, y0, y1) == (40, 61, 30, 51) and not clipped


def test_pixel_box_clips_at_edge():
    (box, clipped) = footprint.pixel_box(wcs_header(50, 50), RA, DEC, 2.0, (50, 50))  # 120 px box, 50 px image
    assert box == (0, 50, 0, 50) and clipped


def test_same_grid_gives_same_box_after_row_shift():
    """A mosaic strip (CRPIX2 shifted by the first fetched row) gives the same box as the full image."""
    full = wcs_header(400, 400)
    (x0, x1, y0, y1), _ = footprint.pixel_box(full, RA, DEC, 0.5, (400, 400))
    strip = full.copy()
    strip["CRPIX2"] -= 150
    (sx0, sx1, sy0, sy1), _ = footprint.pixel_box(strip, RA, DEC, 0.5, (100, 400))
    assert (sx0, sx1, sy0 + 150, sy1 + 150) == (x0, x1, y0, y1)


# ---------- the whole chain ----------
def test_process_cutout_keeps_object_at_same_sky_position(tmp_path):
    data = np.random.default_rng(1).normal(10, 1, (200, 300)).astype(np.float32)
    data[0:5, :] = np.nan  # blank border
    f = raw_fetched(tmp_path, data)
    r = process(f, _product(), TARGET, Options(cutout=True, box_arcmin=1.0))
    assert r.data.shape == (60, 60)
    x, y = WCS(r.header).all_world2pix([[RA, DEC]], 0)[0]
    assert abs(x - 29.5) <= 1 and abs(y - 29.5) <= 1  # within a pixel of the centre
    assert np.isfinite(r.data).all()


def test_header_content(tmp_path):
    data = np.ones((50, 50), dtype=np.float32)
    data[20:22, 20:22] = np.nan
    r = process(raw_fetched(tmp_path, data, notes=["Rows 1-50 fetched."]), _product(), TARGET, Options())
    h = r.header
    assert h["OBJECT"] == "M 51" and h["FILTER"] == "F814W" and h["TELESCOP"] == "HST"
    assert h["PROPOSID"] == 10452 and h["BUNIT"] == "ELECTRONS/S"
    assert h["FFREPAIR"] is True and h["FFNREG"] == 1 and h["FFNPIX"] == 4 and h["FFNBRGT"] == 0
    assert h["FFREPMXB"] == 50_000
    hist = "".join(str(c) for c in h["HISTORY"])
    assert "https://example/x.fits" in hist and "Star-core repair: 1 regions" in hist and "Rows 1-50" in hist
    assert "BSCALE" not in h and "BOFFSET" not in h


def test_mosaics_are_always_cut(product):
    assert Options(cutout=False).for_product(product(is_mosaic=True)).cutout


def test_save_and_compatibility(tmp_path):
    data = np.ones((40, 40), dtype=np.float32)
    r = process(raw_fetched(tmp_path, data), _product(), TARGET, Options())
    out = tmp_path / "out" / "F814W.fits"
    save(r, out)
    assert check_compatible(out) == []
    with fits.open(out) as h:
        assert len(h) == 1 and h[0].header["BITPIX"] == -32


def test_save_refuses_file_without_wcs(tmp_path):
    from fits_fetcher.processing import Result
    with pytest.raises(ProcessingError, match="celestial WCS"):
        save(Result(np.ones((4, 4), np.float32), fits.Header(), []), tmp_path / "bad.fits")
    assert not list(tmp_path.glob("*.fits"))


def test_check_flags_scaled_compressed_multi_hdu(tmp_path):
    p = tmp_path / "c.fits"
    fits.HDUList([fits.PrimaryHDU(), fits.CompImageHDU(np.ones((4, 4), np.float32))]).writeto(p)
    problems = check_compatible(p)
    assert any("HDUs" in x for x in problems)


def test_existing_output_skipped_only_with_same_settings(tmp_path):
    out = tmp_path / "x.fits"
    save(process(raw_fetched(tmp_path, np.ones((40, 40), np.float32)), _product(), TARGET,
                 Options(star_repair=True, repair_max_area=2000)), out)
    assert existing_matches(out, Options(star_repair=True, repair_max_area=2000))
    assert not existing_matches(out, Options(star_repair=True, repair_max_area=500))
    assert not existing_matches(out, Options(star_repair=True, repair_max_area=2000, repair_max_area_bright=9000))
    assert not existing_matches(out, Options(star_repair=False))
    assert not existing_matches(out, Options(cutout=True, box_arcmin=10))
    assert not existing_matches(tmp_path / "missing.fits", Options())


SIRIL = shutil.which("siril-cli") or "/Applications/Siril.app/Contents/MacOS/siril-cli"


@pytest.mark.skipif(not Path(SIRIL).exists(), reason="siril-cli not installed")
def test_output_opens_in_siril(tmp_path):
    """REQ-50: Siril loads the saved file (exit code 0)."""
    data = np.random.default_rng(2).normal(10, 1, (64, 64)).astype(np.float32)
    save(process(raw_fetched(tmp_path, data), _product(), TARGET, Options()), tmp_path / "out.fits")
    (tmp_path / "check.ssf").write_text("requires 1.4.0\nload out.fits\nstat\nclose\n")
    r = subprocess.run([SIRIL, "-d", str(tmp_path), "-s", str(tmp_path / "check.ssf")],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr


def _product():
    from conftest import make_product
    return make_product("F814W")
