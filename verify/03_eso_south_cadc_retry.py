"""Verification 03: ESO with southern objects; CADC reachability retry.
Run: .venv/bin/python verify/03_eso_south_cadc_retry.py
"""
from collections import Counter

import pyvo
from astropy.coordinates import SkyCoord

eso = pyvo.dal.TAPService("https://archive.eso.org/tap_obs")
for name in ["M42", "NGC 7293", "M16"]:
    c = SkyCoord.from_name(name)
    q = (f"SELECT obs_collection, instrument_name, filter, dataproduct_subtype, calib_level, access_estsize, "
         f"obs_release_date, multi_ob, n_obs FROM ivoa.ObsCore WHERE dataproduct_type = 'image' "
         f"AND CONTAINS(POINT('ICRS', {c.ra.deg}, {c.dec.deg}), s_region) = 1")
    t = eso.run_sync(q, maxrec=20000).to_table()
    print(f"\n== ESO {name}: {len(t)} image rows ==")
    for (coll, inst, cl, sub), n in Counter((str(r["obs_collection"]), str(r["instrument_name"]), str(r["calib_level"]), str(r["dataproduct_subtype"])) for r in t).most_common(20):
        rows = t[(t["obs_collection"] == coll) & (t["instrument_name"] == inst)]
        f = sorted({str(v) for v in rows["filter"]})
        print(f"  {coll:16} {inst:10} calib={cl} sub={sub:10} n={n:4} filters: {', '.join(f[:10])}")

print("\n== CADC retry ==")
try:
    cadc = pyvo.dal.TAPService("https://ws-cadc.canfar.net/argus")
    c = SkyCoord.from_name("M51")
    t = cadc.run_sync(f"SELECT obs_collection, instrument_name, calib_level, COUNT(*) AS n FROM ivoa.ObsCore "
                      f"WHERE dataproduct_type='image' AND CONTAINS(POINT('ICRS',{c.ra.deg},{c.dec.deg}), s_region)=1 "
                      f"GROUP BY obs_collection, instrument_name, calib_level").to_table()
    for r in t:
        print(f"  {r['obs_collection']:14} {r['instrument_name']!s:16} calib={r['calib_level']} n={r['n']}")
except Exception as e:
    print(f"  FAILED: {type(e).__name__}: {str(e)[:200]}")
