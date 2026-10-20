"""Live checks against the real archives. Run with: pytest -m network"""
import pytest
import requests

from fits_fetcher.archives.cadc import CadcArchive
from fits_fetcher.archives.eso import EsoArchive
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


def test_m83_eso_sets_and_a_cutout(tmp_path):
    """REQ-90 to REQ-92: M83 has HAWK-I J, H, Ks, BrG stacks and a VHS Y, J, Ks set; one small box downloads."""
    from fits_fetcher.archives.base import Target
    from fits_fetcher.transfer import Transfer

    (t,) = resolve("M83")
    products = EsoArchive(Settings()).search(t, 0.02)
    sets = {s.instruments[0]: {r.filter for r in s.rows} for s in build_sets(products, min_filters=3)}
    assert {"J", "H", "Ks", "BrG"} <= sets["HAWK-I"] and {"Y", "J", "Ks"} <= sets["VIRCAM"]
    small = Target(query="M83", matched_id="M 83", ra=t.ra, dec=t.dec, size_arcmin=1.0)
    p = next(p for p in EsoArchive(Settings()).search(small, 0.02) if p.survey == "VHS")
    f = EsoArchive(Settings()).fetch(p, small, Transfer(tmp_path), 2.0, lambda d, n: None)
    assert abs(f.header["NAXIS1"] - p.width) <= 2 and not f.box_clipped


def test_m87_cadc_sets_a_cutout_and_a_preview(tmp_path):
    """REQ-95 to REQ-98: M87 has a MegaCam set with Hα and [OIII] and a Suprime-Cam set; two filters of one MegaPipe
    tile come back as the same box; a preview is about 200 px."""
    from fits_fetcher.archives.base import Target
    from fits_fetcher.transfer import Transfer

    (t,) = resolve("M87")
    products = CadcArchive(Settings()).search(t, 0.02)
    sets = {s.instruments[0]: {r.filter for r in s.rows} for s in build_sets(products, min_filters=3)}
    assert {"u", "g", "r", "i", "z", "Ha", "OIII"} <= sets["MegaCam"] and {"B", "V", "Rc", "Ic"} <= sets["Suprime-Cam"]
    small = Target(query="M87", matched_id="M 87", ra=t.ra, dec=t.dec, size_arcmin=0.5)
    pair = [p for p in CadcArchive(Settings()).search(small, 0.02)
            if p.obs_id.startswith("MegaPipe.367.205.") and p.filter in ("g", "Ha")]
    heads = [CadcArchive(Settings()).fetch(p, small, Transfer(tmp_path), 2.0, lambda d, n: None).header for p in pair]
    assert len(heads) == 2 and abs(heads[0]["NAXIS1"] - pair[0].width) <= 2
    assert all(heads[0][k] == heads[1][k] for k in ("NAXIS1", "NAXIS2", "CRPIX1", "CRPIX2"))
    assert max(CadcArchive(Settings()).preview(pair[0], t.ra, t.dec, 9.4).shape) <= 200
