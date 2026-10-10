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


def test_quit(client):
    assert client.post("/api/quit").json() == {"ok": True}
    assert client.quit_calls == [1]
