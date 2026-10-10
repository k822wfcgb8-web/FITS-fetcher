"""Live checks against the real archives. Run with: pytest -m network"""
import pytest
import requests

from fits_fetcher.archives.mast import MastArchive
from fits_fetcher.config import Settings
from fits_fetcher.grouping import build_sets
from fits_fetcher.resolve import resolve

pytestmark = pytest.mark.network


def test_m51_resolves_with_size():
    (t,) = resolve("M51")
    assert t.matched_id == "M 51" and t.size_arcmin and t.size_arcmin > 5


def test_crab_lists_candidates():
    ids = {t.matched_id for t in resolve("Crab")}
    assert "M 1" in ids and len(ids) >= 2


def test_m51_mast_sets_and_file_urls_exist():
    (t,) = resolve("M51")
    products = MastArchive(Settings(hst_show_mosaics=True)).search(t, 0.02)
    sets = build_sets(products, min_filters=3)
    assert {"ACS/WFC", "GPC1", "NIRCAM/IMAGE"} <= {i for s in sets for i in s.instruments}
    # One file of each kind must really exist at the address the module built.
    seen = set()
    for p in products:
        kind = (p.collection, p.instrument, p.is_mosaic)
        if kind in seen:
            continue
        seen.add(kind)
        r = requests.head(p.url, allow_redirects=True, timeout=60)
        assert r.status_code == 200, f"{kind}: {p.url}"
