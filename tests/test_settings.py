import json
import subprocess

import pytest
from fastapi.testclient import TestClient

from fits_fetcher import folders
from fits_fetcher.config import Settings, check_folder, validated
from fits_fetcher.web import app as webapp


# ---------- validation (REQ-64, REQ-65) ----------
def test_valid_changes_are_applied_to_a_copy(tmp_path):
    cur = Settings()
    new, errors = validated(cur, {"output_dir": str(tmp_path / "new" / "out"), "parallel_downloads": "5",
                                  "size_warning_gb": "2.5", "mix_instruments": True})
    assert errors == {}
    assert new.output_dir == str(tmp_path / "new" / "out") and (tmp_path / "new" / "out").is_dir()
    assert new.parallel_downloads == 5 and new.size_warning_gb == 2.5 and new.mix_instruments is True
    assert cur.parallel_downloads == 3  # original untouched
    assert new.mast_collections == cur.mast_collections  # file-only settings carried over


@pytest.mark.parametrize("key, value, message", [
    ("parallel_downloads", "0", "between 1 and 10"),
    ("parallel_downloads", "2.5", "whole number"),
    ("min_filters", "1", "between 2 and 20"),
    ("size_warning_gb", "", "Enter a number"),
    ("star_repair_max_area", "abc", "whole number"),
])
def test_bad_numbers(key, value, message):
    _, errors = validated(Settings(), {key: value})
    assert message in errors[key]


def test_folder_checks(tmp_path):
    assert check_folder("relative/path")[1].startswith("Use a full path")
    assert check_folder("  ")[1] == "Enter a folder."
    path, err = check_folder("~/")
    assert err is None and not path.startswith("~")
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0o500)
    try:
        assert "Can't use this folder" in check_folder(str(locked / "sub"))[1]
    finally:
        locked.chmod(0o700)


# ---------- API (REQ-66) ----------
@pytest.fixture
def client(tmp_path):
    settings = Settings(output_dir=str(tmp_path / "out"), cache_dir=str(tmp_path / "cache"))
    path = tmp_path / "config" / "settings.json"
    c = TestClient(webapp.create_app(settings, settings_path=path))
    c.settings, c.path = settings, path
    return c


def test_get_settings_includes_defaults(client):
    body = client.get("/api/settings").json()
    assert body["settings"]["output_dir"].endswith("out")
    assert body["defaults"]["parallel_downloads"] == 3 and "mast_collections" not in body["editable"]


def test_put_saves_file_and_updates_shared_settings(client, tmp_path):
    r = client.put("/api/settings", json={"min_filters": 4, "star_repair": False, "output_dir": str(tmp_path / "o2"),
                                          "mast_collections": ["EVIL"]})
    assert r.status_code == 200
    saved = json.loads(client.path.read_text())
    assert saved["min_filters"] == 4 and saved["star_repair"] is False and saved["mast_collections"] == ["HST", "JWST", "PS1"]
    assert client.settings.min_filters == 4 and client.settings.output_dir == str(tmp_path / "o2")
    assert client.get("/api/info").json()["settings"]["min_filters"] == 4


def test_put_with_errors_changes_nothing(client):
    r = client.put("/api/settings", json={"min_filters": 4, "parallel_downloads": 99})
    assert r.status_code == 422
    assert "parallel_downloads" in r.json()["detail"]["errors"]
    assert client.settings.min_filters == 3 and not client.path.exists()


def test_running_job_keeps_its_settings(client, tmp_path):
    from fits_fetcher.downloads import DownloadManager
    m = DownloadManager(client.settings, {})
    from fits_fetcher.archives.base import Target
    job = m.start(Target("q", "M 51", 1, 2), [], webapp.Options())
    client.settings.output_dir = str(tmp_path / "elsewhere")
    assert job.settings.output_dir.endswith("out")


# ---------- folder dialog (REQ-65) ----------
def test_choose_folder_endpoint(client, monkeypatch):
    monkeypatch.setattr(webapp, "choose_folder", lambda prompt, initial: "/Users/me/Astro")
    assert client.post("/api/choose-folder", json={"initial": "~"}).json() == {"path": "/Users/me/Astro"}
    monkeypatch.setattr(webapp, "choose_folder", lambda prompt, initial: None)
    assert client.post("/api/choose-folder", json={}).json() == {"path": None}

    def none(prompt, initial):
        raise folders.NoFolderDialog("No folder dialog is available here; type the path instead.")
    monkeypatch.setattr(webapp, "choose_folder", none)
    r = client.post("/api/choose-folder", json={})
    assert r.status_code == 501 and "type the path" in r.json()["detail"]


def test_macos_command_quotes_and_starts_at_nearest_existing_folder(monkeypatch, tmp_path):
    monkeypatch.setattr(folders.sys, "platform", "darwin")
    cmd = folders.command('Pick "this"', str(tmp_path / "missing" / "deeper"))
    assert cmd[:4] == ["osascript", "-e", "activate", "-e"]
    assert 'prompt "Pick \\"this\\""' in cmd[4] and f'POSIX file "{tmp_path}"' in cmd[4]


def test_choose_folder_result_and_cancel(monkeypatch):
    monkeypatch.setattr(folders, "command", lambda p, i: ["x"])
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, "/Volumes/Data/Astro/\n", ""))
    assert folders.choose_folder("p", "~") == "/Volumes/Data/Astro"
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 1, "", "User canceled. (-128)"))
    assert folders.choose_folder("p", "~") is None
