import json
import threading
from pathlib import Path

import numpy as np
import pytest
from astropy.io import fits
from fastapi.testclient import TestClient

from fakes import DEC, RA, wcs_header
from fits_fetcher.archives.base import Archive, ArchiveError, Fetched
from fits_fetcher.config import Settings
from fits_fetcher.web import app as webapp

TARGET = {"query": "M51", "matched_id": "M 51", "ra": RA, "dec": DEC, "size_arcmin": 1.0}


def events(text: str) -> list[tuple[str, dict]]:
    out = []
    for block in text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines())
        out.append((lines["event"], json.loads(lines["data"])))
    return out


@pytest.fixture
def setup(monkeypatch, product, tmp_path):
    gate = threading.Event()
    gate.set()

    class Fake(Archive):
        name = "MAST"
        fetches = 0

        def search(self, target, radius_deg):
            return [product(f, obs_id=f"obs_{f}", collection="HST") for f in ("F435W", "F555W", "F814W", "F999W")]

        def fetch(self, p, target, transfer, box_arcmin, progress):
            gate.wait(5)
            transfer.check()
            if p.filter == "F999W":
                raise ArchiveError("file missing at the archive")
            Fake.fetches += 1
            data = np.full((60, 60), 3.0, dtype=">f4")
            path = Path(transfer.cache) / f"{p.obs_id}.bin"
            data.tofile(path)
            progress(data.nbytes, data.nbytes)
            h = wcs_header(60, 60)
            h.update(NAXIS=2, NAXIS1=60, NAXIS2=60, BITPIX=-32)
            return Fetched(fits.Header({"PROPOSID": 10452}), h, path, files=[path])

    monkeypatch.setattr(webapp, "ARCHIVES", {"MAST": Fake})
    settings = Settings(output_dir=str(tmp_path / "out"), cache_dir=str(tmp_path / "cache"))
    c = TestClient(webapp.create_app(settings))
    r = c.get("/api/search", params={"ra": RA, "dec": DEC, "archives": "MAST", "min_filters": 3})
    sets = [d for e, d in events(r.text) if e == "sets"][-1]["sets"]
    return c, sets, Fake, tmp_path / "out" / "M51", gate


def download(c, keys_sets, **opts):
    body = {"target": TARGET, "star_repair": True, "cutout": False, **opts,
            "items": [{"key": k, "sets": s} for k, s in keys_sets]}
    r = c.post("/api/download", json=body)
    assert r.status_code == 200, r.text
    job = r.json()
    ev = events(c.get(f"/api/download/{job['id']}/events").text)
    assert ev[-1][0] == "end"
    return job["id"], ev[-1][1]


def keys(sets):
    return [p["key"] for row in sets[0]["rows"] for p in row["products"]]


def test_download_saves_copies_and_reports(setup):
    c, sets, Fake, obj, _ = setup
    ks = keys(sets)
    job_id, end = download(c, [(ks[0], ["SetA", "SetB"]), (ks[1], ["SetA"]), (ks[3], ["SetA"])])
    states = {it["key"]: it["state"] for it in end["items"]}
    assert states == {ks[0]: "saved", ks[1]: "saved", ks[3]: "failed"}
    assert end["counts"]["saved"] == 2 and end["counts"]["failed"] == 1
    assert "file missing" in next(it["message"] for it in end["items"] if it["key"] == ks[3])
    a, b = obj / "SetA" / "F435W_ACS-WFC_obs_F435W.fits", obj / "SetB" / "F435W_ACS-WFC_obs_F435W.fits"
    assert a.exists() and b.exists()           # one product, copied into each set folder (S-29)
    assert (obj / "CREDITS.txt").exists()      # REQ-30
    assert not list((obj.parent.parent / "cache" / "downloads").glob("obs_F435W*"))  # REQ-23: cache file deleted
    assert c.get(f"/api/download/{job_id}/thumb", params={"key": ks[0]}).content[:4] == b"\x89PNG"


def test_second_download_skips_unless_settings_change(setup):
    c, sets, Fake, obj, _ = setup
    k = keys(sets)[0]
    download(c, [(k, ["SetA"])])
    _, end = download(c, [(k, ["SetA"])])
    assert end["items"][0]["state"] == "skipped" and Fake.fetches == 1
    _, end = download(c, [(k, ["SetA"])], star_repair=False)   # REQ-54: different settings → done again
    assert end["items"][0]["state"] == "saved" and Fake.fetches == 2
    assert fits.getheader(obj / "SetA" / "F435W_ACS-WFC_obs_F435W.fits")["FFREPAIR"] is False


def test_unknown_keys_are_refused(setup):
    c, *_ = setup
    r = c.post("/api/download", json={"target": TARGET, "star_repair": True, "cutout": False,
                                      "items": [{"key": "MAST:HST:evil:F1", "sets": []}]})
    assert r.status_code == 400


def test_cancel(setup):
    c, sets, Fake, obj, gate = setup
    gate.clear()  # hold the fetches until Cancel has been pressed
    ks = keys(sets)
    r = c.post("/api/download", json={"target": TARGET, "star_repair": True, "cutout": False,
                                      "items": [{"key": k, "sets": ["S"]} for k in ks]})
    job_id = r.json()["id"]
    assert c.post(f"/api/download/{job_id}/cancel").json() == {"ok": True}
    gate.set()
    end = events(c.get(f"/api/download/{job_id}/events").text)[-1][1]
    assert end["cancelled"] and {it["state"] for it in end["items"]} == {"cancelled"}
    assert not obj.exists()


def test_open_folder_needs_saved_files(setup, monkeypatch):
    c, sets, *_ = setup
    opened = []
    monkeypatch.setattr(webapp, "open_folder", opened.append)
    job_id, _ = download(c, [(keys(sets)[3], ["S"])])  # fails, so nothing saved
    assert c.post(f"/api/download/{job_id}/open").status_code == 404
    job_id, _ = download(c, [(keys(sets)[0], ["S"])])
    assert c.post(f"/api/download/{job_id}/open").json() == {"ok": True} and opened[0].name == "M51"
