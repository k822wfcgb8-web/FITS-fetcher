import json
import threading
from pathlib import Path

import numpy as np
import pytest
from astropy.io import fits
from fastapi.testclient import TestClient

from fakes import DEC, RA, wcs_header
from fits_fetcher.archives.base import Archive, ArchiveError, Fetched, Target
from fits_fetcher.config import Settings
from fits_fetcher.processing import Options
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


def test_grid_box_found_in_files_saved_earlier(tmp_path, product):
    from fits_fetcher.downloads import DownloadJob
    from fits_fetcher.processing import grid_id

    settings = Settings(output_dir=str(tmp_path), cache_dir=str(tmp_path / "cache"))
    target = Target(query="NGC 3675", matched_id="NGC 3675", ra=1, dec=2)
    p = product("F450W", grid="visit 1")
    job = DownloadJob(target, [], Options(), settings, {})
    assert job._grid_box(p) is None
    saved = job.object_dir / "Set" / "F336W.fits"
    saved.parent.mkdir(parents=True)
    fits.PrimaryHDU(np.zeros((2, 2), np.float32),
                    fits.Header({"FFGRID": grid_id(p), "FFTRIMBX": "-10 10 -5 5"})).writeto(saved)
    job._grid_boxes.clear()
    assert DownloadJob(target, [], Options(), settings, {})._grid_box(p) == "-10 10 -5 5"
    assert DownloadJob(target, [], Options(), settings, {})._grid_box(product("F450W", grid="visit 2")) is None


def test_data_mask_saved_and_copied_with_each_image(setup):
    c, sets, Fake, obj, _ = setup
    k = keys(sets)[0]
    _, end = download(c, [(k, ["SetA", "SetB"])], data_mask=True)
    assert end["items"][0]["state"] == "saved"
    for s in ("SetA", "SetB"):
        image = next(x for x in (obj / s).glob("*.fits") if not x.name.endswith("_mask.fits"))
        mask = image.with_name(image.stem + "_mask.fits")
        assert mask.exists() and fits.getheader(image)["FFDMASK"] is True
        with fits.open(mask) as hdul:
            assert [x.name for x in hdul] == ["DATA", "GAPS"] and (hdul[0].data == 255).all()
    _, end = download(c, [(k, ["SetA"])], data_mask=True)
    assert end["items"][0]["state"] == "skipped"
    next((obj / "SetA").glob("*_mask.fits")).unlink()
    _, end = download(c, [(k, ["SetA"])], data_mask=True)  # the mask went missing: download again
    assert end["items"][0]["state"] == "saved" and Fake.fetches == 2


def test_grid_mask_written_for_images_on_one_grid(setup, monkeypatch, product):
    from fits_fetcher.downloads import DownloadJob, Item
    from fits_fetcher.masks import grid_mask_path
    from fits_fetcher.processing import grid_id

    c, sets, Fake, obj, _ = setup
    a, b = product("F555W", grid="visit 1"), product("F814W", grid="visit 1")
    job = DownloadJob(Target(**TARGET), [Item(a, ["S"]), Item(b, ["S"])], Options(data_mask=True),
                      Settings(output_dir=str(obj.parent)), {})
    folder = obj / "S"
    folder.mkdir(parents=True)
    from fits_fetcher.masks import write_mask
    h = fits.Header(wcs_header(30, 30)); h["FFGRID"] = grid_id(a)
    for name in ("F555W.fits", "F814W.fits"):
        write_mask(folder / name.replace(".fits", "_mask.fits"), np.ones((30, 30), bool), h, name, [])
    job._grid_masks([folder / "F814W.fits"], folder / "F814W.fits")
    assert grid_mask_path(folder, "visit 1").exists()
