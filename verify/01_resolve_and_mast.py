"""Verification 01: name resolution (S-09, REQ-04/05/13/18) and MAST access (Section 7.1).

Checks only; downloads nothing. Run: .venv/bin/python verify/01_resolve_and_mast.py
"""
from collections import Counter

import astropy.units as u
from astropy.coordinates import SkyCoord
from astroquery.mast import Observations

NAMES = ["M51", "Whirlpool Galaxy", "NGC 5194", "Orion Nebula", "IC 434", "Horsehead Nebula", "NotARealObject123"]

print("== Name resolution (SkyCoord.from_name / Sesame) ==")
for name in NAMES:
    try:
        c = SkyCoord.from_name(name)
        print(f"  {name!r:24} -> {c.ra.deg:10.5f} {c.dec.deg:+10.5f}")
    except Exception as e:
        print(f"  {name!r:24} -> FAILED: {type(e).__name__}: {e}")

print("\n== MAST: combined (calib_level 3+), public, science images within 0.05 deg of M51 ==")
m51 = SkyCoord.from_name("M51")
obs = Observations.query_criteria(
    coordinates=m51,
    radius=0.05 * u.deg,
    dataproduct_type="image",
    calib_level=[3, 4],
    intentType="science",
    dataRights="PUBLIC",
)
print(f"  {len(obs)} observations")
print("  Columns:", ", ".join(obs.colnames))
by_inst = Counter((r["obs_collection"], r["instrument_name"]) for r in obs)
for (coll, inst), n in by_inst.most_common(25):
    filters = sorted({str(r["filters"]) for r in obs if r["obs_collection"] == coll and r["instrument_name"] == inst})
    print(f"  {coll:10} {inst:22} {n:4} obs  filters: {', '.join(filters[:12])}{' ...' if len(filters) > 12 else ''}")

print("\n== Footprint field (needed for REQ-14 'contains centre') ==")
print("  s_region example:", str(obs[0]["s_region"])[:150])

print("\n== Product list for one HST observation (science-file naming, REQ-15/S-14) ==")
hst = obs[(obs["obs_collection"] == "HST")]
if len(hst):
    prods = Observations.get_product_list(hst[:1])
    for p in prods:
        print(f"  {p['productFilename']:45} {p['productSubGroupDescription']!s:8} {p['productType']!s:10} calib={p['calib_level']} size={p['size']}")
