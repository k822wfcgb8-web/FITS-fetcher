"""Test doubles: an HTTP session serving bytes with Range support, and small FITS files with a real WCS."""
from __future__ import annotations

import io

import numpy as np
from astropy.io import fits

RA, DEC = 202.4696, 47.1953


class FakeResponse:
    def __init__(self, body: bytes, status: int, headers: dict, fail_after: int | None = None):
        self.body, self.status_code, self.headers, self.fail_after = body, status, headers, fail_after

    @property
    def content(self) -> bytes:
        return self.body

    def iter_content(self, size):
        import requests
        for i in range(0, len(self.body), size):
            if self.fail_after is not None and i >= self.fail_after:
                raise requests.ConnectionError("simulated drop")
            yield self.body[i:i + size]

    def raise_for_status(self):
        import requests
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} error")

    def close(self):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass


class FakeSession:
    """Serves `files` (url → bytes). `ranges=False` ignores Range headers, like a server without support."""

    def __init__(self, files: dict[str, bytes], ranges: bool = True):
        self.files, self.ranges = files, ranges
        self.requests: list[tuple[str, str | None]] = []
        self.drop_next_after: int | None = None

    def get(self, url, headers=None, stream=False, timeout=None):
        rng = (headers or {}).get("Range")
        self.requests.append((url, rng))
        if url not in self.files:
            return FakeResponse(b"", 404, {})
        body = self.files[url]
        drop, self.drop_next_after = self.drop_next_after, None
        if rng and self.ranges:
            first, last = rng.removeprefix("bytes=").split("-")
            last = int(last) if last else len(body) - 1
            part = body[int(first):last + 1]
            return FakeResponse(part, 206, {"Content-Length": str(len(part))}, drop)
        return FakeResponse(body, 200, {"Content-Length": str(len(body))}, drop)


def wcs_header(nx: int, ny: int, scale_arcsec: float = 1.0, ra: float = RA, dec: float = DEC) -> fits.Header:
    h = fits.Header()
    h["CTYPE1"], h["CTYPE2"] = "RA---TAN", "DEC--TAN"
    h["CRVAL1"], h["CRVAL2"] = ra, dec
    h["CRPIX1"], h["CRPIX2"] = (nx + 1) / 2, (ny + 1) / 2
    h["CD1_1"], h["CD2_2"] = -scale_arcsec / 3600, scale_arcsec / 3600
    h["CD1_2"] = h["CD2_1"] = 0.0
    return h


def hst_like_file(data: np.ndarray, scale_arcsec: float = 1.0) -> bytes:
    """Primary header with instrument keywords, then SCI, then a WHT extension (like an HST _drc)."""
    primary = fits.PrimaryHDU()
    primary.header["TELESCOP"] = "HST"
    primary.header["INSTRUME"] = "ACS"
    primary.header["PROPOSID"] = 10452
    primary.header["EXPTIME"] = 1360.0
    sci = fits.ImageHDU(data.astype(">f4"), wcs_header(data.shape[1], data.shape[0], scale_arcsec), name="SCI")
    sci.header["BUNIT"] = "ELECTRONS/S"
    wht = fits.ImageHDU(np.ones_like(data, dtype=">f4"), name="WHT")
    buf = io.BytesIO()
    fits.HDUList([primary, sci, wht]).writeto(buf)
    return buf.getvalue()
