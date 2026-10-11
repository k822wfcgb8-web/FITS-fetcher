"""Verification 16: why M35 showed one colour set, and the off-centre same-grid sets (REQ-71).

Counts M35's MAST images at each selection stage, then lists the off-centre sets the app builds.
Run: .venv/bin/python verify/16_offcentre_sets.py [object]
"""
import sys
import time
from collections import Counter

import astropy.units as u
from astropy.coordinates import SkyCoord
from astroquery.mast import Observations

from fits_fetcher import filters, footprint, spots
from fits_fetcher.archives import mast as M
from fits_fetcher.config import Settings
from fits_fetcher.resolve import resolve

name = sys.argv[1] if len(sys.argv) > 1 else "M35"
t = resolve(name)[0]
print(t)
archive = M.MastArchive(Settings())

# ---- where the images go (radius = the object's own) ----
rows = Observations.query_criteria(coordinates=SkyCoord(t.ra * u.deg, t.dec * u.deg), radius=t.size_arcmin / 2 * u.arcmin,
                                   obs_collection=["HST", "JWST", "PS1"], dataproduct_type="image", calib_level=[3],
                                   intentType="science", dataRights="PUBLIC")
stages = [("combined, public, allowed instruments", lambda r: M._allowed(M._text(r["obs_collection"]), M._text(r["instrument_name"]))),
          ("HST duplicates removed (REQ-58)", archive._wanted_family),
          ("usable single filter", lambda r: bool(filters.effective_filter(M._text(r["filters"])))),
          ("footprint contains the centre (REQ-14)", lambda r: footprint.contains(M._text(r["s_region"]), t.ra, t.dec))]
for label, keep in stages:
    rows = [r for r in rows if keep(r)]
    print(f"{len(rows):6d}  {label}")
print("        by instrument:", Counter(M._text(r["instrument_name"]) for r in rows))

# ---- off-centre sets ----
t0 = time.time()
candidates = archive.elsewhere(t)
t1 = time.time()
sets = spots.build(candidates, t, min_filters=3)
print(f"\n{len(candidates)} candidates (query {t1 - t0:.1f} s), {len(sets)} off-centre sets ({time.time() - t1:.1f} s)")
for cs in sets:
    p = cs.position
    exp = ", ".join(f"{r.filter} {r.products[0].exptime_s:.0f}s" for r in cs.rows)
    print(f"  {p['offset_arcmin']:4.1f}' {p['direction']:2s} {p['area_arcmin2']:5.2f} arcmin²  {' + '.join(cs.instruments)}: {exp}"
          f"  [{cs.grids[0].grid}]")
