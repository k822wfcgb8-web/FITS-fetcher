"""HTTP downloads for the download step: whole files and byte ranges, resumable and cancellable.

- Pieces are written to the cache folder as `<hash>.part` and renamed when complete, so an interrupted
  download continues where it stopped (S-27). The caller deletes the files once the output is saved (REQ-23).
- `locate_hdu` reads FITS headers one after another with range requests to find where the science
  extension's data lie, so only that extension is fetched (REQ-57). Verified for MAST and PS1 on 2026-10-10
  (both answer `Range` requests with 206).
"""
from __future__ import annotations

import hashlib
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import requests
from astropy.io import fits

log = logging.getLogger(__name__)

BLOCK = 2880                  # FITS block size
CHUNK = 1 << 20               # bytes per read while streaming
HEADER_READ = 10 * BLOCK      # bytes asked for per header request
TIMEOUT = (30, 120)           # connect, read (seconds)
ATTEMPTS = 3                  # tries per piece; each retry resumes from the bytes already saved

Progress = Callable[[int, int], None]  # (bytes done, bytes total)


class TransferError(Exception):
    """A download failed after retries, or the server answered with something unusable."""


class Cancelled(Exception):
    """The user pressed Cancel (S-07)."""


@dataclass
class HduLocation:
    primary: fits.Header
    header: fits.Header
    data_offset: int          # byte offset of the HDU's data in the file
    data_size: int            # unpadded data size in bytes


def data_size(header: fits.Header) -> int:
    """Size of an HDU's data in bytes, without the padding to a whole block (FITS standard 4.4.1)."""
    naxis = header.get("NAXIS", 0)
    if not naxis:
        return 0
    n = 1
    for i in range(1, naxis + 1):
        n *= header.get(f"NAXIS{i}", 0)
    return abs(header["BITPIX"]) // 8 * header.get("GCOUNT", 1) * (header.get("PCOUNT", 0) + n)


def _padded(n: int) -> int:
    return -(-n // BLOCK) * BLOCK


class Transfer:
    """Downloads for one job. Shared by worker threads; each call is independent."""

    def __init__(self, cache_dir: str | Path, cancel: threading.Event | None = None,
                 session: requests.Session | None = None):
        self.cache = Path(cache_dir) / "downloads"
        self.cache.mkdir(parents=True, exist_ok=True)
        self.cancel = cancel or threading.Event()
        self.session = session or requests.Session()

    def check(self) -> None:
        if self.cancel.is_set():
            raise Cancelled()

    # ---------- headers ----------
    def read_header(self, url: str, offset: int) -> tuple[fits.Header, int]:
        """Read the FITS header starting at `offset`; returns it and its length in bytes (whole blocks)."""
        raw = b""
        while True:
            self.check()
            r = self._get(url, offset + len(raw), offset + len(raw) + HEADER_READ - 1)
            chunk = r.content
            if r.status_code == 200:  # range ignored: the whole file is coming; keep only what we asked for
                chunk = chunk[offset + len(raw): offset + len(raw) + HEADER_READ]
            if not chunk:
                raise TransferError(f"No FITS header at byte {offset} of {url}")
            start = len(raw)
            raw += chunk
            for pos in range(start - start % 80, len(raw) - 79, 80):
                if raw[pos:pos + 8] == b"END     ":
                    length = _padded(pos + 80)
                    return fits.Header.fromstring(raw[:pos + 80].decode("ascii", "replace")), length
            if len(chunk) < HEADER_READ:
                raise TransferError(f"FITS header at byte {offset} of {url} has no END card")

    def locate_hdu(self, url: str, want: int | str) -> HduLocation:
        """Find an HDU by index or EXTNAME by walking the headers (no data are read)."""
        offset, index, primary = 0, 0, None
        while True:
            header, length = self.read_header(url, offset)
            if primary is None:
                primary = header
            name = str(header.get("EXTNAME", "PRIMARY" if index == 0 else "")).strip().upper()
            if want == index or (isinstance(want, str) and name == want.upper()):
                return HduLocation(primary, header, offset + length, data_size(header))
            offset += length + _padded(data_size(header))
            index += 1
            if index > 50:
                raise TransferError(f"Extension {want!r} not found in {url}")

    # ---------- data ----------
    def fetch(self, url: str, start: int = 0, length: int | None = None, progress: Progress | None = None,
              suffix: str = "") -> Path:
        """Download bytes [start, start + length) of `url` (the whole file if length is None) into the cache.

        Resumes a partial download left by an earlier attempt. Returns the completed file.
        """
        key = hashlib.sha1(f"{url}|{start}|{length}".encode()).hexdigest()[:20]
        done_path = self.cache / f"{key}{suffix}"
        if done_path.exists() and (length is None or done_path.stat().st_size == length):
            if progress:
                progress(done_path.stat().st_size, done_path.stat().st_size)
            return done_path
        part = done_path.with_name(done_path.name + ".part")
        for attempt in range(1, ATTEMPTS + 1):
            try:
                self._stream(url, start, length, part, progress)
                part.replace(done_path)
                return done_path
            except (Cancelled, TransferError):
                raise
            except (requests.RequestException, OSError) as e:
                if attempt == ATTEMPTS:
                    raise TransferError(f"Download failed after {ATTEMPTS} tries: {e}") from e
                log.warning("Download of %s interrupted (%s); retrying", url, e)
                time.sleep(2 * attempt)
        raise AssertionError("unreachable")

    def _stream(self, url: str, start: int, length: int | None, part: Path, progress: Progress | None) -> None:
        have = part.stat().st_size if part.exists() else 0
        end = start + length - 1 if length is not None else None
        if length is not None and have >= length:
            return
        r = self._get(url, start + have, end, stream=True)
        if r.status_code == 200 and (start + have) > 0:
            r.close()
            if length is not None:
                raise TransferError(f"{url} doesn't support partial downloads")
            have = 0  # server restarted from the beginning: so do we
            r = self._get(url, 0, None, stream=True)
        total = length if length is not None else have + int(r.headers.get("Content-Length") or 0)
        with r, open(part, "ab" if have else "wb") as f:
            for chunk in r.iter_content(CHUNK):
                self.check()
                f.write(chunk)
                have += len(chunk)
                if progress:
                    progress(have, max(total, have))
        if length is not None and have < length:
            raise requests.ConnectionError(f"connection closed after {have} of {length} bytes")

    def _get(self, url: str, first: int, last: int | None, stream: bool = False) -> requests.Response:
        headers = {}
        if first or last is not None:
            headers["Range"] = f"bytes={first}-{'' if last is None else last}"
        r = self.session.get(url, headers=headers, stream=stream, timeout=TIMEOUT)
        if r.status_code not in (200, 206):
            r.close()
            raise TransferError(f"{url} answered HTTP {r.status_code}")
        return r
