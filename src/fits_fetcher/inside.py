"""Identify the objects behind archive target names for the "Also inside" list (REQ-70).

Archives name their targets freely ("NGC-2438", "SN2005CS", "QXPUP", "M51-POS4", "ANY"). One SIMBAD query
looks all the names up (exact identifiers, about 0.4 s for 13 names on 2026-10-10), so that:
- spellings and aliases of one object merge into one entry ("SN2005CS" = "SN-2005CS"; "QX PUP" = OH 231.8+04.2);
- the searched object itself is dropped ("M51" when searching M 51);
- unknown labels are dropped ("M51-POS4", "ANY"), unless their images point at a known object in the list,
  in which case they join it.
If SIMBAD can't be reached, the archive names are listed as they are.
"""
from __future__ import annotations

import logging
import re


from fits_fetcher import filters, footprint
from fits_fetcher.archives.base import InsideGroup, InsideObject, Target
from fits_fetcher.resolve import simbad

log = logging.getLogger(__name__)
SAME_OBJECT_ARCSEC = 10   # a known object this close to the searched centre is the searched object
JOIN_ARCSEC = 30          # images of an unknown name pointing this close to a known object belong to it


def search_name(target_name: str) -> str:
    """An archive target name made searchable: 'NGC-2438' → 'NGC 2438', 'OH231.8+04.2' → 'OH 231.8+04.2'."""
    return re.sub(r"^([A-Za-z]+)[-_ ]?(?=\d)", r"\1 ", target_name.strip())


def variants(name: str) -> list[str]:
    """Spellings to look up. Variable-star names lose their space in archives: 'QXPUP' → 'QX PUP'."""
    out = {search_name(name)}
    if m := re.fullmatch(r"([A-Za-z]{1,2})([A-Za-z]{3})", name.strip()):
        out.add(f"{m[1]} {m[2]}")
    return sorted(out)


def norm(identifier: str) -> str:
    """Compare identifiers ignoring case, spaces and SIMBAD's 'V*' / '*' / 'NAME' prefixes."""
    s = re.sub(r"^(v\*|\*+|name)\s+", "", identifier.strip().lower())
    return re.sub(r"\s+", "", s)


def display(main_id: str) -> str:
    return re.sub(r"^NAME\s+", "", " ".join(main_id.split()))


def lookup(names: list[str]) -> dict[str, tuple[str, float, float]]:
    """norm(identifier) → (SIMBAD main identifier, ra, dec) for every name SIMBAD knows."""
    if not names:
        return {}
    ids = ", ".join("'" + n.replace("'", "''") + "'" for n in names)
    rows = simbad().search(
        f"SELECT i.id, b.main_id, b.ra, b.dec FROM ident AS i JOIN basic AS b ON b.oid = i.oidref WHERE i.id IN ({ids})")
    return {norm(str(r["id"])): (str(r["main_id"]), float(r["ra"]), float(r["dec"]))
            for r in rows if r["ra"] is not None and str(r["ra"]) != "--"}


def _arcsec(ra1, dec1, ra2, dec2) -> float:
    return footprint.angular_sep_deg(ra1, dec1, ra2, dec2) * 3600


def _offset(ra, dec, target: Target) -> float:
    return footprint.angular_sep_deg(ra, dec, target.ra, target.dec) * 60


def identify(groups: list[InsideGroup], target: Target) -> list[InsideObject]:
    try:
        known = lookup(sorted({v for g in groups for v in variants(g.name)}))
    except Exception as e:  # SIMBAD unreachable: list the archive names as they are
        log.warning("Couldn't identify target names with SIMBAD: %s", e)
        return sorted((InsideObject(g.name, g.ra, g.dec, _offset(g.ra, g.dec, target), [g]) for g in groups),
                      key=lambda o: o.offset_arcmin)

    objects: dict[str, InsideObject] = {}
    unknown = []
    for g in groups:
        hit = next((known[norm(v)] for v in variants(g.name) if norm(v) in known), None)
        if hit is None:
            unknown.append(g)
            continue
        main_id, ra, dec = hit
        if norm(main_id) == norm(target.matched_id) or _arcsec(ra, dec, target.ra, target.dec) < SAME_OBJECT_ARCSEC:
            continue  # the searched object itself
        obj = objects.setdefault(main_id, InsideObject(display(main_id), ra, dec, _offset(ra, dec, target)))
        obj.sets.append(g)
    for g in unknown:
        near = [o for o in objects.values()
                if _arcsec(o.ra, o.dec, g.ra, g.dec) <= JOIN_ARCSEC
                or any(_arcsec(s.ra, s.dec, g.ra, g.dec) <= JOIN_ARCSEC for s in o.sets)]
        if near:
            near[0].sets.append(g)

    for obj in objects.values():  # one line per archive and instrument
        merged: dict[tuple[str, str], InsideGroup] = {}
        for s in obj.sets:
            m = merged.setdefault((s.archive, s.instrument), InsideGroup(obj.name, s.archive, s.instrument, [], s.ra, s.dec, s.collection))
            m.filters = sorted(set(m.filters) | set(s.filters), key=lambda f: filters.parse(f, s.instrument)[0] or 99)
        obj.sets = sorted(merged.values(), key=lambda s: (-len(s.filters), s.instrument))
    return sorted(objects.values(), key=lambda o: (o.offset_arcmin, o.name))
