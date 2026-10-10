import pytest

from fits_fetcher import footprint

# A 0.2° square around M51 (202.47, +47.20).
SQUARE = "POLYGON ICRS 202.37 47.10 202.57 47.10 202.57 47.30 202.37 47.30"


def test_polygon_contains_centre():
    assert footprint.contains(SQUARE, 202.47, 47.20)


def test_polygon_excludes_point_outside():
    assert not footprint.contains(SQUARE, 202.70, 47.20)
    assert not footprint.contains(SQUARE, 202.47, 47.40)


def test_polygon_without_frame_keyword():
    assert footprint.contains(SQUARE.replace("ICRS ", ""), 202.47, 47.20)


def test_polygon_across_ra_zero():
    region = "POLYGON 359.9 0.1 0.1 0.1 0.1 -0.1 359.9 -0.1"
    assert footprint.contains(region, 0.0, 0.0)
    assert footprint.contains(region, 359.95, 0.0)
    assert not footprint.contains(region, 180.0, 0.0)


def test_any_of_several_polygons():
    region = "POLYGON 10 10 10.1 10 10.1 10.1 10 10.1 POLYGON 202.37 47.10 202.57 47.10 202.57 47.30 202.37 47.30"
    assert footprint.contains(region, 202.47, 47.20)


def test_circle():
    assert footprint.contains("CIRCLE ICRS 202.47 47.20 0.05", 202.50, 47.21)
    assert not footprint.contains("CIRCLE ICRS 202.47 47.20 0.05", 202.70, 47.20)


@pytest.mark.parametrize("bad", ["", "--", "garbage", "POLYGON 1 2"])
def test_unparseable_regions_do_not_match(bad):
    assert not footprint.contains(bad, 202.47, 47.20)


def test_area_of_square():
    # 0.2° of RA at Dec 47.2 is 0.2·cos(47.2°) ≈ 0.136° wide, times 0.2° high.
    assert footprint.area_deg2(SQUARE) == pytest.approx(0.2 * 0.2 * 0.6794, rel=0.01)


def test_area_of_unparseable_region_is_none():
    assert footprint.area_deg2("") is None
