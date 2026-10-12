import json
import time

import pytest
from fastapi.testclient import TestClient

from fits_fetcher.archives import ArchiveError
from fits_fetcher.archives.base import Archive, Target
from fits_fetcher.config import Settings
from fits_fetcher.web import app as webapp


def events(text: str) -> list[tuple[str, dict]]:
    out = []
    for block in text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines())
        out.append((lines["event"], json.loads(lines["data"])))
    return out


@pytest.fixture
def client(monkeypatch, product):
    class Good(Archive):
        name = "GOOD"
        def search(self, target, radius_deg):
            return [product("F435W"), product("F555W"), product("F814W")]

    class Broken(Archive):
        name = "BROKEN"
        def search(self, target, radius_deg):
            raise ArchiveError("service unavailable")

    class Slow(Archive):
        name = "SLOW"
        def search(self, target, radius_deg):
            time.sleep(2)
            return []

    monkeypatch.setattr(webapp, "ARCHIVES", {"GOOD": Good, "BROKEN": Broken, "SLOW": Slow})
    quit_calls = []
    app = webapp.create_app(Settings(archive_timeout_s=1), on_quit=lambda: quit_calls.append(1))
    c = TestClient(app)
    c.quit_calls = quit_calls
    return c


def test_page_and_info(client):
    assert "FITS-fetcher" in client.get("/").text
    info = client.get("/api/info").json()
    assert info["archives"] == ["GOOD", "BROKEN", "SLOW"]
    assert "Hα" in info["emission_lines"]
    for path in ("/", "/static/app.js", "/static/style.css"):  # always revalidated, so updates show at once
        assert client.get(path).headers["cache-control"] == "no-cache"


def test_resolve(client, monkeypatch):
    monkeypatch.setattr(webapp, "resolve", lambda q: [Target(query=q, matched_id="M 51", ra=1, dec=2)])
    assert client.get("/api/resolve", params={"q": "M51"}).json()["targets"][0]["matched_id"] == "M 51"


def test_resolve_failure_is_404_with_message(client, monkeypatch):
    def fail(q):
        raise webapp.ResolveError("No object called 'zz' was found.")
    monkeypatch.setattr(webapp, "resolve", fail)
    r = client.get("/api/resolve", params={"q": "zz"})
    assert r.status_code == 404 and "No object" in r.json()["detail"]


def test_search_streams_results_and_reports_failures(client):
    r = client.get("/api/search", params={"ra": 1, "dec": 2, "archives": "GOOD,BROKEN,SLOW,UNKNOWN"})
    ev = events(r.text)
    states = {d["archive"]: d["state"] for e, d in ev if e == "status" and d["state"] != "searching"}
    assert states == {"GOOD": "done", "BROKEN": "failed", "SLOW": "timeout"}
    sets = [d for e, d in ev if e == "sets"][-1]["sets"]
    assert len(sets) == 1 and len(sets[0]["rows"]) == 3
    assert ev[-1][0] == "end"


def test_info_has_telescope_fact_sheets(client):
    info = client.get("/api/info").json()
    assert info["archive_telescopes"] == {}  # neither MAST nor IRSA is among this test's archives
    ps1 = info["telescopes"]["PS1"]
    assert ps1["name"] == "Pan-STARRS1" and ps1["facts"] and ps1["artifacts"] and ps1["link"].startswith("https://")


def test_search_only_ticked_mast_telescopes(monkeypatch, product):
    seen = []

    class Mast(Archive):
        name = "MAST"
        def search(self, target, radius_deg):
            seen.append(self.settings.mast_collections)
            return []

    monkeypatch.setattr(webapp, "ARCHIVES", {"MAST": Mast})
    settings = Settings()
    c = TestClient(webapp.create_app(settings))
    c.get("/api/search", params={"ra": 1, "dec": 2, "archives": "MAST", "telescopes": "PS1,HST"})
    c.get("/api/search", params={"ra": 1, "dec": 2, "archives": "MAST"})  # no choice sent: all of them
    assert seen == [["HST", "PS1"], ["HST", "JWST", "PS1"]]
    assert settings.mast_collections == ["HST", "JWST", "PS1"]  # the saved settings are untouched

    ev = events(c.get("/api/search", params={"ra": 1, "dec": 2, "archives": "MAST", "telescopes": ""}).text)
    assert ("status", {"archive": "MAST", "state": "skipped", "message": "MAST: no telescope ticked."}) in ev
    assert len(seen) == 2 and ev[-1][0] == "end"


def test_irsa_telescopes_get_tick_boxes_too(monkeypatch):
    """REQ-87: each archive with telescopes gets its own tick boxes; one `telescopes` list covers all of them."""
    seen = {}

    def fake(name, field):
        class A(Archive):
            def search(self, target, radius_deg):
                seen[name] = getattr(self.settings, field)
                return []
        A.name = name
        return A

    monkeypatch.setattr(webapp, "ARCHIVES", {"MAST": fake("MAST", "mast_collections"),
                                             "IRSA": fake("IRSA", "irsa_collections")})
    c = TestClient(webapp.create_app(Settings()))
    info = c.get("/api/info").json()
    assert info["archive_telescopes"] == {"MAST": ["HST", "JWST", "PS1"],
                                          "IRSA": ["spitzer_seip", "wise_allwise", "twomass_allsky"]}
    assert info["telescopes"]["wise_allwise"]["name"] == "WISE" and "IRSA" in info["telescopes"]["wise_allwise"]["link_label"]
    ev = events(c.get("/api/search", params={"ra": 1, "dec": 2, "archives": "MAST,IRSA", "telescopes": "JWST,wise_allwise"}).text)
    assert seen == {"MAST": ["JWST"], "IRSA": ["wise_allwise"]}
    ev = events(c.get("/api/search", params={"ra": 1, "dec": 2, "archives": "MAST,IRSA", "telescopes": "HST"}).text)
    assert ("status", {"archive": "IRSA", "state": "skipped", "message": "IRSA: no telescope ticked."}) in ev


def test_quit(client):
    assert client.post("/api/quit").json() == {"ok": True}
    assert client.quit_calls == [1]


def test_objects_inside_streamed_after_results_for_sized_objects(monkeypatch, product):
    from fits_fetcher.archives.base import InsideGroup, InsideObject

    group = InsideGroup("NGC-2438", "GOOD", "WFPC2/PC", ["F502N", "F656N", "F658N"], 1.0, 2.1)

    class WithInside(Archive):
        name = "GOOD"
        def search(self, target, radius_deg):
            return [product(f) for f in ("F435W", "F555W", "F814W")]
        def inside(self, target, min_filters):
            return [group]

    monkeypatch.setattr(webapp, "ARCHIVES", {"GOOD": WithInside})
    monkeypatch.setattr(webapp, "identify", lambda groups, target: [InsideObject("NGC 2438", 1.0, 2.1, 6.0, groups)])
    c = TestClient(webapp.create_app(Settings()))
    ev = events(c.get("/api/search", params={"ra": 1, "dec": 2, "archives": "GOOD", "size_arcmin": 25}).text)
    names = [e for e, _ in ev]
    assert names.index("sets") < names.index("inside") and names[-1] == "end"
    done = [d for e, d in ev if e == "inside"][-1]
    assert done["state"] == "done" and done["objects"][0]["name"] == "NGC 2438"
    assert done["objects"][0]["sets"][0]["instrument"] == "WFPC2/PC"
    ev = events(c.get("/api/search", params={"ra": 1, "dec": 2, "archives": "GOOD"}).text)  # size unknown
    assert "inside" not in [e for e, _ in ev]


def test_download_gives_each_image_its_grid_footprints(monkeypatch, product):
    on_grid = [product(f, grid="visit 1", region=f"POLYGON {i} 0 1 0 1 1") for i, f in enumerate(("F435W", "F555W"))]
    lone = product("F814W")

    class Good(Archive):
        name = "GOOD"
        def search(self, target, radius_deg):
            return [*on_grid, lone]

    monkeypatch.setattr(webapp, "ARCHIVES", {"GOOD": Good})
    app = webapp.create_app(Settings())
    started = []
    monkeypatch.setattr(webapp.DownloadManager, "start", lambda self, target, items, options: started.extend(items) or
                        type("Job", (), {"snapshot": lambda self: {}})())
    c = TestClient(app)
    c.get("/api/search", params={"ra": 1, "dec": 2, "archives": "GOOD", "min_filters": 2})
    target = {"query": "x", "matched_id": "X", "ra": 1, "dec": 2}
    c.post("/api/download", json={"target": target, "star_repair": False, "cutout": False,
                                  "items": [{"key": on_grid[0].key}, {"key": lone.key}]})
    assert started[0].product.grid_regions == sorted(p.region for p in on_grid)  # its partner's too, not downloaded
    assert started[1].product.grid_regions == []
