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

_IRSA = ("This research has made use of the NASA/IPAC Infrared Science Archive, which is funded by the National "
         "Aeronautics and Space Administration and operated by the California Institute of Technology.")

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
    # IRSA: its own statement (irsa.ipac.caltech.edu/ack.html), then each mission's, checked 2026-10-12 on the IRSA
    # 2MASS page and the AllWISE release page. IRSA's Spitzer pages give none, so Spitzer's is the standard text.
    "spitzer_seip": ("Spitzer Space Telescope",
                     "This work is based in part on observations made with the Spitzer Space Telescope, which was "
                     "operated by the Jet Propulsion Laboratory, California Institute of Technology under a contract "
                     "with NASA. " + _IRSA),
    "wise_allwise": ("Wide-field Infrared Survey Explorer (AllWISE)",
                     "This publication makes use of data products from AllWISE. AllWISE makes use of data from WISE, "
                     "which is a joint project of the University of California, Los Angeles, and the Jet Propulsion "
                     "Laboratory/California Institute of Technology, and NEOWISE, which is a project of the Jet "
                     "Propulsion Laboratory/California Institute of Technology. WISE and NEOWISE are funded by the "
                     "National Aeronautics and Space Administration. " + _IRSA),
    "twomass_allsky": ("Two Micron All Sky Survey (2MASS)",
                       "This publication makes use of data products from the Two Micron All Sky Survey, which is a "
                       "joint project of the University of Massachusetts and the Infrared Processing and Analysis "
                       "Center/California Institute of Technology, funded by the National Aeronautics and Space "
                       "Administration and the National Science Foundation. " + _IRSA),
}

# ESO (REQ-90): its data access policy (archive.eso.org/cms/eso-data-access-policy.html, checked 2026-10-12) asks
# for the programme statement and, for processed data, the DOI of the data collection, listed at
# archive.eso.org/wdb/wdb/doi/collections/query. Keyed by the collection (FFSURVEY), e.g. "VHS".
ESO_DOI = {
    "VHS": 57, "VVV": 67, "VVVX": 68, "VMC": 64, "VIKING": 59, "VIDEO": 58, "VINROUGE": 61, "VISIONS": 63,
    "GCAV": 26, "SHARKS": 75, "UltraVISTA": 52, "KIDS": 37, "OMEGACAM_INAF": 98, "FDS": 23, "ARP_VST": 99,
    "VEGAS": 54, "HAWKI": 34, "HUGS": 35, "195.B-0283": 9, "092.A-0472": 7, "60.A-9284H": 13, "PESSTO": 46,
    "ePESSTOplus": 86,
}
_ESO = ("Based on observations collected at the European Southern Observatory under ESO programme(s) {programs}, "
        "and/or processed data created thereof.")
for _coll, _doi in ESO_DOI.items():
    CREDITS[_coll] = (f"ESO {_coll}", _ESO + f" Based on data obtained from the ESO Science Archive Facility with "
                                             f"DOI: https://doi.org/10.18727/archive/{_doi}.")

# CADC (REQ-95): CADC's own acknowledgement (cadc-ccda.hia-iha.nrc-cnrc.gc.ca/en/about.html), after the observatory's
# standard one for each instrument, plus the paper describing the stacking pipeline. Keyed by the CADC collection
# (FFSURVEY).
_CADC = ("This research used the facilities of the Canadian Astronomy Data Centre operated by the National Research "
         "Council of Canada with the support of the Canadian Space Agency.")
_CFHT = ("at the Canada-France-Hawaii Telescope (CFHT) which is operated by the National Research Council (NRC) of "
         "Canada, the Institut National des Sciences de l'Univers of the Centre National de la Recherche Scientifique "
         "(CNRS) of France, and the University of Hawaii.")
CREDITS.update({
    "CFHTMEGAPIPE": ("CFHT MegaCam (MegaPipe stacks, CADC)",
                     "Based on observations obtained with MegaPrime/MegaCam, a joint project of CFHT and CEA/DAPNIA, "
                     + _CFHT + " Stacks made by MegaPipe (Gwyn 2008, PASP 120, 212). " + _CADC),
    "CFHTWIRWOLF": ("CFHT WIRCam (WIRWOLF stacks, CADC)",
                    "Based on observations obtained with WIRCam, a joint project of CFHT, Taiwan, Korea, Canada and "
                    "France, " + _CFHT + " " + _CADC),
    "SUBARUCADC": ("Subaru Suprime-Cam (CADC stacks)",
                   "Based on data collected at Subaru Telescope, which is operated by the National Astronomical "
                   "Observatory of Japan, and obtained from the SMOKA archive and the Canadian Astronomy Data Centre. "
                   + _CADC),
})


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
    if str(header.get("PROG_ID", "")).strip():  # ESO, e.g. '179.A-2010(K)'; leading zeros belong to it
        return str(header["PROG_ID"]).strip()
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
        coll = h.get("FFSURVEY") or h.get("FFCOLL")  # ESO credits each data collection (REQ-90)
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
    return preview_png(img)


def preview_png(img: np.ndarray) -> bytes:
    """A display-only PNG of a small image: asinh stretch, north up as stored (REQ-27, REQ-98)."""
    img = np.asarray(img, dtype=np.float64)
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
