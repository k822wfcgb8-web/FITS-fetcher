"""Verification 04: listing candidate objects for an ambiguous name (REQ-18).

SkyCoord.from_name (Sesame) returns one position only. This tests SIMBAD's TAP service.
Finding (first attempt): a contains-anywhere search, lowercase(id) LIKE '%term%', ran >10 minutes and was
abandoned; SIMBAD's ADQL also lacks LOWER/UPPER/ILIKE. This version uses starts-with matches on the
'NAME ...' identifiers, trying the term as typed and in Title Case.
Run: .venv/bin/python verify/04_name_candidates.py
"""
import time

import pyvo

simbad = pyvo.dal.TAPService("https://simbad.cds.unistra.fr/simbad/sim-tap")
TESTS = ["Crab", "Eagle", "Ring Nebula", "Whirlpool", "Horsehead", "Pinwheel", "Orion", "orion nebula"]

for term in TESTS:
    variants = sorted({term, term.title()})
    cond = " OR ".join(f"ident.id LIKE 'NAME {v}%'" for v in variants)
    q = ("SELECT TOP 20 main_id, otype, ra, dec, ident.id AS matched "
         f"FROM ident JOIN basic ON ident.oidref = basic.oid WHERE {cond} ORDER BY main_id")
    t0 = time.time()
    try:
        t = simbad.run_sync(q, timeout=60).to_table()
    except Exception as e:
        print(f"{term!r}: FAILED after {time.time()-t0:.1f}s {type(e).__name__}: {str(e)[:150]}")
        continue
    print(f"\n{term!r}: {len(t)} candidates in {time.time()-t0:.1f}s")
    for r in t:
        print(f"   {r['main_id']!s:28} {r['otype']!s:6} {r['ra']:10.4f} {r['dec']:+9.4f}   matched: {r['matched']}")
