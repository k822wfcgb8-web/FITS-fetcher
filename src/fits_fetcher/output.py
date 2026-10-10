"""Where outputs go (S-29), the per-object credits file (REQ-30) and thumbnails made after download (REQ-27)."""
from __future__ import annotations

import datetime as dt
import hashlib
import re
import struct
import textwrap
import zlib
from collections import defaultdict
from pathlib import Path

import numpy as np
from astropy.io import fits

from fits_fetcher import __version__
from fits_fetcher.archives.base import Product, Target

MAX_NAME = 120  # keep folder names well under the 255-character limit of common file systems

# Acknowledgements requested by each mission, checked against the MAST and PS1 pages on 2026-10-10:
# archive.stsci.edu/publishing/mission-acknowledgements and the PS1 data archive home page.
CREDITS = {
    "HST": ("Hubble Space Telescope",
            "This research is based on observations made with the NASA/ESA Hubble Space Telescope obtained from "
            "the Space Telescope Science Institute, which is operated by the Association of Universities for "
            "Research in Astronomy, Inc., under NASA contract NAS 5-26555. These observations are associated "
            "with program(s) {programs}."),
    "JWST": ("James Webb Space Telescope",
             "This work is based on observations made with the NASA/ESA/CSA James Webb Space Telescope. The data "
             "were obtained from the Mikulski Archive for Space Telescopes at the Space Telescope Science "
             "Institute, which is operated by the Association of Universities for Research in Astronomy, Inc., "
             "under NASA contract NAS 5-03127 for JWST. These observations are associated with program(s) "
             "{programs}."),
    "PS1": ("Pan-STARRS1",
            "The Pan-STARRS1 Surveys (PS1) and the PS1 public science archive have been made possible through "
            "contributions by the Institute for Astronomy, the University of Hawaii, the Pan-STARRS Project "
            "Office, the Max-Planck Society and its participating institutes, the Max Planck Institute for "
            "Astronomy, Heidelberg and the Max Planck Institute for Extraterrestrial Physics, Garching, The Johns "
            "Hopkins University, Durham University, the University of Edinburgh, the Queen's University Belfast, "
            "the Harvard-Smithsonian Center for Astrophysics, the Las Cumbres Observatory Global Telescope Network "
            "Incorporated, the National Central University of Taiwan, the Space Telescope Science Institute, the "
            "National Aeronautics and Space Administration under Grant No. NNX08AR22G issued through the "
            "Planetary Science Division of the NASA Science Mission Directorate, the National Science Foundation "
            "Grant No. AST-1238877, the University of Maryland, Eotvos Lorand University (ELTE), the Los Alamos "
            "National Laboratory, and the Gordon and Betty Moore Foundation. Please also cite Chambers et al. "
            "2016, \"The Pan-STARRS1 Surveys\" (arXiv:1612.05560)."),
}


def safe(name: str) -> str:
    """A file or folder name that works on macOS, Linux and Windows."""
    name = re.sub(r"[^A-Za-z0-9._+-]+", "_", name.replace("/", "-")).strip("._")
    if len(name) > MAX_NAME:
        name = name[:MAX_NAME - 9] + "_" + hashlib.sha1(name.encode()).hexdigest()[:8]
    return name or "unnamed"


def object_folder(target: Target) -> str:
    """'M 51' → 'M51', 'NGC 5194' → 'NGC5194', 'NAME Orion Bar' → 'Orion_Bar'; typed coordinates by position."""
    if target.matched_id in ("", "(coordinates entered)"):
        return safe(f"RA{target.ra:.4f}_Dec{target.dec:+.4f}")
    name = re.sub(r"^NAME\s+", "", target.matched_id)
    name = re.sub(r"^([A-Za-z]+)\s+(?=\d)", r"\1", name)
    return safe(name)


def file_name(product: Product) -> str:
    """S-29: <Filter>_<Instrument>_<ObsID>.fits"""
    return f"{safe(product.filter)}_{safe(product.instrument)}_{safe(product.obs_id)}.fits"


def output_paths(output_dir: str | Path, target: Target, product: Product, set_names: list[str]) -> list[Path]:
    """One path per colour set the product belongs to (S-29: copied into each set folder)."""
    base = Path(output_dir).expanduser() / object_folder(target)
    return [base / safe(s) / file_name(product) for s in (set_names or ["Unsorted"])]


# ---------- credits (REQ-30) ----------
def _programme(header: fits.Header) -> str:
    for key in ("PROPOSID", "PROGRAM"):
        if str(header.get(key, "")).strip():
            return str(header[key]).strip().lstrip("0") or "0"
    m = re.match(r"(?:hst_|jw)0*(\d+)", str(header.get("FFOBSID", "")).lower())
    return m.group(1) if m else ""


def write_credits(object_dir: Path) -> Path | None:
    """Rebuild CREDITS.txt from every FITS-fetcher file in the object's folder."""
    files = sorted(p for p in object_dir.rglob("*.fits") if not p.name.endswith(".partial.fits"))
    by_coll: dict[str, set[str]] = defaultdict(set)
    listing = []
    for p in files:
        try:
            h = fits.getheader(p)
        except (OSError, ValueError):
            continue
        coll = h.get("FFCOLL")
        if not coll:
            continue
        prog = _programme(h)
        if prog:
            by_coll[coll].add(prog)
        else:
            by_coll.setdefault(coll, set())
        listing.append(f"  {p.relative_to(object_dir)}  ({h.get('FFARCH', '?')} {coll} {h.get('FFOBSID', '')})")
    if not listing:
        return None
    lines = [f"Credits for {object_dir.name}",
             f"Written by FITS-fetcher {__version__} on {dt.date.today().isoformat()}.",
             "Include these acknowledgements when you publish images made from these files.", ""]
    for coll in sorted(by_coll):
        title, text = CREDITS.get(coll, (coll, "Data from the {coll} collection; see the archive's acknowledgement policy."))
        progs = ", ".join(sorted(by_coll[coll], key=lambda s: (len(s), s))) or "(see the file headers)"
        lines += [title, *textwrap.wrap(text.format(programs=progs, coll=coll), 100), ""]
    lines += ["Files:", *listing, ""]
    path = object_dir / "CREDITS.txt"
    path.write_text("\n".join(lines))
    return path


# ---------- thumbnails (REQ-27) ----------
def thumbnail_png(path: Path, size: int = 128) -> bytes:
    """A small display-only PNG of a saved output: strided sample, asinh stretch, north up as stored."""
    with fits.open(path, memmap=True) as h:
        data = h[0].data
        step = max(1, -(-max(data.shape) // size))
        img = np.array(data[::step, ::step], dtype=np.float64)
    finite = img[np.isfinite(img) & (img != 0)]
    if finite.size:
        lo, hi = np.percentile(finite, [1, 99.7])
        x = np.clip((img - lo) / (hi - lo or 1), 0, 1)
        x = np.arcsinh(10 * x) / np.arcsinh(10)
    else:
        x = np.zeros_like(img)
    pixels = (np.nan_to_num(x) * 255).astype(np.uint8)[::-1]  # FITS row 1 is the bottom
    return _png(pixels)


def _png(gray: np.ndarray) -> bytes:
    h, w = gray.shape
    raw = b"".join(b"\x00" + gray[y].tobytes() for y in range(h))

    def chunk(kind: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 0, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))
