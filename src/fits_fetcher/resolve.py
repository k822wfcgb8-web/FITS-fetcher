"""Object name → coordinates (REQ-04/05/13/18, S-09/S-10/S-11).

- Catalogue designations and exact names go to CDS Sesame (`SkyCoord.from_name`); it returns one position.
- Catalogue designations (M51, NGC 5194) always go to Sesame: a starts-with search on 'M51' also matches
  unrelated SIMBAD names such as 'M51 OT2019-1' (a transient).
- To list several candidates for a common name (REQ-18), SIMBAD's TAP service is searched for
  'NAME …' identifiers that start with the typed text. Verification step 04 found that contains-anywhere
  matching takes minutes, that SIMBAD's ADQL lacks LOWER/UPPER/ILIKE, and that OR-ing case variants in one
  query is slow, so each case variant is a separate starts-with query.
- Planets and major moons (REQ-78) aren't in SIMBAD: 'saturn' matched only 'NAME Saturn Nebula' (NGC 7009). A
  body's name is listed first, with SIMBAD's matches for the same text after it.
- SIMBAD calls give up after 15 s (REQ-77): on 2026-10-11 SIMBAD stopped answering and "Find object" hung. Once
  SIMBAD has failed, the lookup carries on with Sesame's position alone (Sesame has its own mirror and time limit).
"""
from __future__ import annotations

import logging
import re
from dataclasses import replace

import pyvo
import requests
from astropy import units as u
from astropy.coordinates import SkyCoord
from astropy.coordinates.name_resolve import NameResolveError

from fits_fetcher import solar
from fits_fetcher.archives.base import Target

log = logging.getLogger(__name__)
SIMBAD_TAP = "https://simbad.cds.unistra.fr/simbad/sim-tap"
MAX_CANDIDATES = 20
SIMBAD_TIMEOUT_S = 15
NO_SIMBAD_NOTE = ("SIMBAD didn't answer, so this object's size is unknown: the search can't show whole-object boxes, "
                  "off-centre sets or other objects inside it. Try again later for those.")

_COORDS = re.compile(r"^\s*[-+]?\d")
# Catalogue designations: letters then a number, e.g. M51, M 51, NGC 5194, IC 434, Sh2-155, HD 1234.
_DESIGNATION = re.compile(r"^\s*[A-Za-z][A-Za-z0-9]{0,7}[\s-]*\d")


class ResolveError(Exception):
    """The name couldn't be resolved; the user should enter RA/Dec instead (REQ-13)."""


class SimbadUnavailable(Exception):
    """SIMBAD failed or didn't answer within SIMBAD_TIMEOUT_S."""


class _TimeoutSession(requests.Session):
    """A requests session with a default time limit; pyvo's TAP calls have none of their own."""

    def __init__(self, timeout: float):
        super().__init__()
        self.timeout = timeout

    def request(self, method, url, **kwargs):
        kwargs.setdefault("timeout", self.timeout)
        return super().request(method, url, **kwargs)


def simbad() -> pyvo.dal.TAPService:
    """SIMBAD's TAP service, giving up after SIMBAD_TIMEOUT_S (REQ-77)."""
    return pyvo.dal.TAPService(SIMBAD_TAP, session=_TimeoutSession(SIMBAD_TIMEOUT_S))


def parse_coordinates(text: str) -> Target | None:
    """Accept 'RA Dec' typed directly (S-11): decimal degrees or sexagesimal. None if it isn't coordinates."""
    if not _COORDS.match(text):
        return None
    try:
        parts = text.replace(",", " ").split()
        if len(parts) == 2 and all(_is_float(p) for p in parts):
            c = SkyCoord(float(parts[0]) * u.deg, float(parts[1]) * u.deg)
        else:
            c = SkyCoord(text, unit=(u.hourangle, u.deg))
    except (ValueError, u.UnitsError):
        return None
    return Target(query=text, matched_id="(coordinates entered)", ra=c.ra.deg, dec=c.dec.deg)


def _is_float(s: str) -> bool:
    try:
        float(s)
        return True
    except ValueError:
        return False


def _escape(s: str) -> str:
    return s.replace("'", "''")


def candidates(text: str, service: pyvo.dal.TAPService | None = None) -> list[Target]:
    """SIMBAD objects with a 'NAME …' identifier starting with `text` (as typed, and in Title Case).
    Raises SimbadUnavailable at the first failure, without trying the other case variant."""
    service = service or simbad()
    found: dict[str, Target] = {}
    for variant in dict.fromkeys([text.strip(), text.strip().title()]):
        q = (f"SELECT TOP {MAX_CANDIDATES} main_id, otype, ra, dec, galdim_majaxis "
             "FROM ident JOIN basic ON ident.oidref = basic.oid "
             f"WHERE ident.id LIKE 'NAME {_escape(variant)}%'")
        try:
            rows = service.run_sync(q).to_table()
        except Exception as e:  # network or service error: the caller falls back to Sesame only
            log.warning("SIMBAD candidate search failed for %r: %s", variant, e)
            raise SimbadUnavailable(str(e)) from e
        for r in rows:
            main_id = " ".join(str(r["main_id"]).split())
            if main_id in found or _masked(r["ra"]) or _masked(r["dec"]):
                continue  # duplicates (several names, one object) and objects without coordinates
            size = None if _masked(r["galdim_majaxis"]) else float(r["galdim_majaxis"])
            found[main_id] = Target(query=text, matched_id=main_id, ra=float(r["ra"]), dec=float(r["dec"]),
                                    object_type=str(r["otype"]), size_arcmin=size)
    return list(found.values())


def _masked(v) -> bool:
    return v is None or getattr(v, "mask", False) is True or str(v) in ("--", "nan")


def sesame(text: str, details: bool = True) -> Target:
    """Sesame's position for `text`, with SIMBAD's details unless SIMBAD has already failed (`details` False)."""
    try:
        c = SkyCoord.from_name(text)
    except NameResolveError as e:
        raise ResolveError(f"No object called '{text}' was found. You can enter RA and Dec instead.") from e
    t = Target(query=text, matched_id=text, ra=float(c.ra.deg), dec=float(c.dec.deg))
    return _with_simbad_details(t) if details else replace(t, note=NO_SIMBAD_NOTE)


def _with_simbad_details(t: Target, service: pyvo.dal.TAPService | None = None) -> Target:
    """Add SIMBAD's main identifier, object type and size (for S-10 and S-12) for the object at Sesame's
    position. Best effort: on any failure the target is returned with a note that its size is unknown."""
    service = service or simbad()
    q = ("SELECT TOP 1 main_id, otype, galdim_majaxis, "
         f"DISTANCE(POINT('ICRS', ra, dec), POINT('ICRS', {t.ra}, {t.dec})) AS dist FROM basic "
         f"WHERE CONTAINS(POINT('ICRS', ra, dec), CIRCLE('ICRS', {t.ra}, {t.dec}, 0.0003)) = 1 ORDER BY dist")
    try:
        rows = service.run_sync(q).to_table()
    except Exception as e:
        log.warning("SIMBAD details lookup failed for %s: %s", t.query, e)
        return replace(t, note=NO_SIMBAD_NOTE)
    if not len(rows):
        return t
    r = rows[0]
    size = None if _masked(r["galdim_majaxis"]) else float(r["galdim_majaxis"])
    return Target(query=t.query, matched_id=" ".join(str(r["main_id"]).split()), ra=t.ra, dec=t.dec,
                  object_type=str(r["otype"]), size_arcmin=size)


def resolve(text: str) -> list[Target]:
    """All plausible targets for what the user typed. One entry means no choice is needed (REQ-18)."""
    text = text.strip()
    if not text:
        raise ResolveError("Enter an object name or coordinates.")
    coords = parse_coordinates(text)
    if coords:
        return [coords]
    planet = solar.body(text)
    if planet:
        try:
            others = _named(text)
        except ResolveError:
            others = []
        return [planet] + others
    return _named(text)


def _named(text: str) -> list[Target]:
    """Objects outside the Solar System called `text`, from Sesame and SIMBAD."""
    if _DESIGNATION.match(text):
        # A designation names one object; a starts-with search would also match e.g. 'M51 OT2019-1'.
        return [sesame(text)]
    try:
        found = candidates(text)
    except SimbadUnavailable:
        return [sesame(text, details=False)]
    if found:
        return found
    return [sesame(text)]
