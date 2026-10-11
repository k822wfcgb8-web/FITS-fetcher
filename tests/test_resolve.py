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
    monkeypatch.setattr(resolve, "sesame", lambda text, details=True: calls.append(("sesame", text)) or t)
    monkeypatch.setattr(resolve, "candidates", lambda text: calls.append(("simbad", text)) or [t, t])
    return calls


@pytest.mark.parametrize("text", ["M51", "M 51", "NGC 5194", "IC 434", "Sh2-155", "HD 1234"])
def test_designations_go_to_sesame_only(routes, text):
    assert len(resolve.resolve(text)) == 1
    assert routes == [("sesame", text)]


def test_common_names_get_candidates(routes):
    assert len(resolve.resolve("Crab")) == 2
    assert routes == [("simbad", "Crab")]


@pytest.mark.parametrize("text, name, kind", [
    ("saturn", "Saturn", "Planet"), ("  JUPITER ", "Jupiter", "Planet"), ("Pluto", "Pluto", "Dwarf planet"),
    ("titan", "Titan", "Moon of Saturn"), ("Moon", "Moon", "Moon of Earth"),
])
def test_planets_and_moons_come_first(routes, text, name, kind):
    """REQ-78: 'saturn' used to resolve only to the Saturn Nebula (NGC 7009)."""
    found = resolve.resolve(text)
    assert (found[0].matched_id, found[0].object_type, found[0].body) == (name, kind, name)
    assert len(found) == 3  # SIMBAD's matches for the same text follow
    assert routes == [("simbad", text.strip())]


def test_planet_alone_when_nothing_else_matches(monkeypatch):
    def nothing(text):
        raise resolve.ResolveError("no")
    monkeypatch.setattr(resolve, "_named", nothing)
    assert [t.matched_id for t in resolve.resolve("Neptune")] == ["Neptune"]


def test_saturn_nebula_is_not_the_planet(routes):
    assert all(not t.body for t in resolve.resolve("Saturn Nebula"))


def test_empty_input():
    with pytest.raises(resolve.ResolveError):
        resolve.resolve("   ")


# ---------- SIMBAD not answering (REQ-77) ----------
@pytest.fixture
def silent_simbad(monkeypatch):
    """A local server that accepts connections and never answers, like SIMBAD on 2026-10-11."""
    import socket
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(5)
    monkeypatch.setattr(resolve, "SIMBAD_TAP", f"http://127.0.0.1:{srv.getsockname()[1]}/tap")
    monkeypatch.setattr(resolve, "SIMBAD_TIMEOUT_S", 1)
    yield
    srv.close()


def test_silent_simbad_gives_up_after_the_time_limit(silent_simbad):
    import time
    t0 = time.monotonic()
    with pytest.raises(resolve.SimbadUnavailable):
        resolve.candidates("Helix Nebula")
    assert time.monotonic() - t0 < 5  # one query, one time limit: no second case variant tried


def test_common_name_falls_back_to_sesame_without_details(silent_simbad, monkeypatch):
    from astropy.coordinates import SkyCoord
    monkeypatch.setattr(SkyCoord, "from_name", classmethod(lambda cls, name: SkyCoord(337.41, -20.84, unit="deg")))
    (t,) = resolve.resolve("Helix Nebula")
    assert (t.ra, t.dec) == pytest.approx((337.41, -20.84)) and t.size_arcmin is None
    assert "SIMBAD didn't answer" in t.note


def test_details_lookup_failure_leaves_a_note(silent_simbad):
    t = resolve._with_simbad_details(Target(query="NGC 7293", matched_id="NGC 7293", ra=337.41, dec=-20.84))
    assert t.matched_id == "NGC 7293" and "size is unknown" in t.note
