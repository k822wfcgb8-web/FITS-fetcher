import threading

import numpy as np
import pytest

from fakes import FakeSession, hst_like_file
from fits_fetcher.transfer import Cancelled, Transfer, TransferError, data_size

URL = "https://archive.example/file.fits"


@pytest.fixture
def file_bytes():
    return hst_like_file(np.arange(200 * 300, dtype=np.float32).reshape(200, 300))


def test_locate_hdu_finds_sci_without_reading_data(tmp_path, file_bytes):
    s = FakeSession({URL: file_bytes})
    loc = Transfer(tmp_path, session=s).locate_hdu(URL, "SCI")
    assert loc.primary["TELESCOP"] == "HST" and loc.header["EXTNAME"] == "SCI"
    assert loc.data_size == 200 * 300 * 4 == data_size(loc.header)
    got = np.frombuffer(file_bytes[loc.data_offset:loc.data_offset + loc.data_size], ">f4")
    assert got[0] == 0 and got[-1] == 200 * 300 - 1
    assert all(r is not None for _, r in s.requests)  # only range requests: the data were never fetched


def test_locate_hdu_by_index(tmp_path, file_bytes):
    loc = Transfer(tmp_path, session=FakeSession({URL: file_bytes})).locate_hdu(URL, 2)
    assert loc.header["EXTNAME"] == "WHT"


def test_fetch_range_with_progress_and_cache_reuse(tmp_path, file_bytes):
    s = FakeSession({URL: file_bytes})
    t = Transfer(tmp_path, session=s)
    seen = []
    path = t.fetch(URL, 5760, 10_000, progress=lambda d, n: seen.append((d, n)))
    assert path.read_bytes() == file_bytes[5760:15760]
    assert seen[-1] == (10_000, 10_000)
    n = len(s.requests)
    assert t.fetch(URL, 5760, 10_000) == path and len(s.requests) == n  # already complete: no new request


def test_fetch_resumes_after_dropped_connection(tmp_path, file_bytes, monkeypatch):
    monkeypatch.setattr("fits_fetcher.transfer.time.sleep", lambda s: None)
    monkeypatch.setattr("fits_fetcher.transfer.CHUNK", 4096)
    s = FakeSession({URL: file_bytes})
    s.drop_next_after = 8192
    path = Transfer(tmp_path, session=s).fetch(URL)
    assert path.read_bytes() == file_bytes
    assert s.requests[-1][1] == "bytes=8192-"  # second attempt continued from the saved bytes


def test_fetch_range_needs_server_support(tmp_path, file_bytes):
    with pytest.raises(TransferError, match="partial"):
        Transfer(tmp_path, session=FakeSession({URL: file_bytes}, ranges=False)).fetch(URL, 5760, 100)


def test_http_error_is_reported(tmp_path):
    with pytest.raises(TransferError, match="404"):
        Transfer(tmp_path, session=FakeSession({})).fetch(URL)


def test_cancel_stops_download(tmp_path, file_bytes):
    ev = threading.Event()
    ev.set()
    with pytest.raises(Cancelled):
        Transfer(tmp_path, cancel=ev, session=FakeSession({URL: file_bytes})).fetch(URL)
