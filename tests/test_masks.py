"""Data masks (REQ-101 to REQ-103)."""
import numpy as np
import pytest
from astropy.io import fits

from fakes import wcs_header
from fits_fetcher.masks import (ON, combine_grid, gap_layer, gap_radius_px, grid_mask_path, mask_path,
                                pixel_scale_arcsec, write_mask)
from fits_fetcher.processing import Options, existing_matches, process, save
from test_processing import TARGET, _product, raw_fetched


def _field_with_gap(n=400, margin=40, gap=(190, 226)) -> np.ndarray:
    """A square field with a blank border and a vertical 36 px gap through it, like a WFC3/UVIS chip gap."""
    data = np.zeros((n, n), dtype=bool)
    data[margin:n - margin, margin:n - margin] = True
    data[:, gap[0]:gap[1]] = False
    return data


def test_gap_layer_marks_the_chip_gap_but_not_the_border():
    data = _field_with_gap()
    gaps = gap_layer(data, 0.04)
    assert gaps[40:360, 190:226].all()          # the gap inside the field
    assert not gaps[:40].any() and not gaps[:, :40].any() and not gaps[:, 360:].any()  # the border
    assert not (gaps & data).any()


def test_gap_layer_ignores_a_strip_wider_than_the_limit():
    data = _field_with_gap(n=600, gap=(200, 320))  # 120 px at 0.04″ = 4.8″, wider than GAP_MAX_ARCSEC
    assert not gap_layer(data, 0.04).any()


def test_gap_layer_closes_a_diagonal_gap():
    data = _field_with_gap(gap=(0, 0))
    y, x = np.mgrid[:400, :400]
    data[np.abs(x - y) < 18] = False            # a 45° strip about 25 px wide
    gaps = gap_layer(data, 0.04)
    assert gaps[200, 200] and gaps[100, 100]
    assert not gaps[10, 10]                     # where the strip runs out through the border


def test_gap_layer_skips_corner_roundings_and_scales_with_pixels():
    data = np.zeros((400, 400), dtype=bool)
    data[40:360, 40:360] = True
    data[40:200, 40:200] = False                # an L-shaped field: its inside corner isn't a gap
    assert not gap_layer(data, 0.04).any()
    assert gap_radius_px(0.25) < gap_radius_px(0.04)


def test_process_records_the_data_before_nan_becomes_zero(tmp_path):
    data = np.full((60, 60), 5.0, dtype=np.float32)
    data[:, :10] = np.nan                       # blank border
    data[30, 30] = np.nan                       # a star-core hole, repaired
    r = process(raw_fetched(tmp_path, data), _product(), TARGET, Options(star_repair=True, data_mask=True))
    assert r.mask is not None and r.mask.shape == r.data.shape
    assert r.mask.all()                         # the blank border was trimmed; the repaired core counts as data
    assert r.header["FFDMASK"] is True
    off = process(raw_fetched(tmp_path, data), _product(), TARGET, Options())
    assert off.mask is None and off.header["FFDMASK"] is False


def test_mask_file_has_data_and_gaps_layers(tmp_path):
    h = wcs_header(400, 400, scale_arcsec=0.04)
    h["FILTER"], h["FFGRID"] = "F555W", "abc"
    path = tmp_path / "F555W_mask.fits"
    n = write_mask(path, _field_with_gap(), h, "F555W.fits", [])
    with fits.open(path) as hdul:
        assert [x.name for x in hdul] == ["DATA", "GAPS"]
        assert hdul[0].data.dtype == np.uint8 and set(np.unique(hdul[0].data)) == {0, ON}
        assert (hdul[1].data == ON).sum() == n > 0
        assert hdul[0].header["FFIMAGE"] == "F555W.fits" and hdul[0].header["FFGRID"] == "abc"
        assert pixel_scale_arcsec(hdul[1].header) == pytest.approx(0.04)


def test_a_wanted_mask_that_is_missing_means_downloading_again(tmp_path):
    out = tmp_path / "x.fits"
    r = process(raw_fetched(tmp_path, np.ones((40, 40), np.float32)), _product(), TARGET, Options(data_mask=True))
    save(r, out)
    assert not existing_matches(out, Options(data_mask=True))     # no mask file yet
    write_mask(mask_path(out), r.mask, r.header, out.name, [])
    assert existing_matches(out, Options(data_mask=True))
    assert existing_matches(out, Options())                       # a mask you no longer want doesn't matter


def test_files_saved_before_masks_existed_are_kept(tmp_path):
    path = tmp_path / "old.fits"
    h = fits.Header([(k, v, c) for k, v, c in Options().cards() if k != "FFDMASK"])
    fits.PrimaryHDU(np.zeros((2, 2), np.float32), h).writeto(path)
    assert existing_matches(path, Options())
    assert not existing_matches(path, Options(data_mask=True))


def test_grid_mask_keeps_data_present_in_every_filter(tmp_path):
    h = wcs_header(400, 400, scale_arcsec=0.04)
    h["FFGRID"] = "g1"
    a = _field_with_gap()
    b = _field_with_gap(gap=(200, 236))          # the same field, the gap a few pixels over
    write_mask(tmp_path / "F555W_mask.fits", a, h, "F555W.fits", [])
    assert combine_grid(tmp_path, "g1", "HST skycell p1773x11y07") is None      # one image: nothing to combine
    write_mask(tmp_path / "F814W_mask.fits", b, h, "F814W.fits", [])
    write_mask(tmp_path / "F350LP_mask.fits", np.ones((10, 10), bool), h, "F350LP.fits", [])  # grew: left out
    other = h.copy(); other["FFGRID"] = "g2"
    write_mask(tmp_path / "J_mask.fits", np.zeros((400, 400), bool), other, "J.fits", [])     # another grid
    path = combine_grid(tmp_path, "g1", "HST skycell p1773x11y07")
    assert path == grid_mask_path(tmp_path, "HST skycell p1773x11y07")
    assert path.name == "Grid_HST_skycell_p1773x11y07_mask.fits"
    with fits.open(path) as hdul:
        assert np.array_equal(hdul[0].data > 0, a & b)
        assert hdul["GAPS"].data[200, 190:236].all()  # the union of both gaps
        assert hdul[0].header["FFNIMG"] == 2
        assert "F350LP_mask.fits" in "".join(str(c) for c in hdul[0].header["HISTORY"])


def test_gap_reaches_the_field_edge_when_the_border_is_narrow():
    data = _field_with_gap(margin=16)            # REQ-75 trims to the data plus 16 px
    gaps = gap_layer(data, 0.04)
    assert gaps[16:384, 190:226].all()
    assert not gaps[:16].any() and not gaps[384:].any() and not gaps[:, :16].any()
