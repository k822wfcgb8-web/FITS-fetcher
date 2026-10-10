import pytest

from fits_fetcher import resolve
from fits_fetcher.archives.base import Target


@pytest.mark.parametrize("text, ra, dec", [
    ("202.47 47.195", 202.47, 47.195),
    ("202.47, -47.195", 202.47, -47.195),
    ("13h29m52.7s +47d11m43s", 202.4696, 47.1953),
    ("13 29 52.7 +47 11 43", 202.4696, 47.1953),
])
def test_coordinates(text, ra, dec):
    t = resolve.parse_coordinates(text)
    assert t.ra == pytest.approx(ra, abs=1e-3) and t.dec == pytest.approx(dec, abs=1e-3)


@pytest.mark.parametrize("text", ["M51", "Whirlpool", "NGC 5194"])
def test_names_are_not_coordinates(text):
    assert resolve.parse_coordinates(text) is None


@pytest.fixture
def routes(monkeypatch):
    calls = []
    t = Target(query="q", matched_id="X", ra=1.0, dec=2.0)
    monkeypatch.setattr(resolve, "sesame", lambda text: calls.append(("sesame", text)) or t)
    monkeypatch.setattr(resolve, "candidates", lambda text: calls.append(("simbad", text)) or [t, t])
    return calls


@pytest.mark.parametrize("text", ["M51", "M 51", "NGC 5194", "IC 434", "Sh2-155", "HD 1234"])
def test_designations_go_to_sesame_only(routes, text):
    assert len(resolve.resolve(text)) == 1
    assert routes == [("sesame", text)]


def test_common_names_get_candidates(routes):
    assert len(resolve.resolve("Crab")) == 2
    assert routes == [("simbad", "Crab")]


def test_empty_input():
    with pytest.raises(resolve.ResolveError):
        resolve.resolve("   ")
