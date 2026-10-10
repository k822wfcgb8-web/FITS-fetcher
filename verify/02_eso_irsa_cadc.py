"""Verification 02: ESO, IRSA and CADC access through their ObsCore TAP services (Section 7.1).

For each archive: combined (calib_level >= 3) images whose footprint contains M51's centre (REQ-14),
summarised by collection/instrument, plus the columns available. Downloads nothing.
Run: .venv/bin/python verify/02_eso_irsa_cadc.py
"""
from collections import Counter

import pyvo
from astropy.coordinates import SkyCoord

SERVICES = {
    "ESO": ("https://archive.eso.org/tap_obs", "ivoa.ObsCore"),
    "IRSA": ("https://irsa.ipac.caltech.edu/TAP", "ivoa.obscore"),
    "CADC": ("https://ws-cadc.canfar.net/argus", "ivoa.ObsCore"),
}

c = SkyCoord.from_name("M51")
ra, dec = c.ra.deg, c.dec.deg

for name, (url, table) in SERVICES.items():
    print(f"\n===== {name}  ({url}) =====")
    try:
        svc = pyvo.dal.TAPService(url)
        adql = (
            f"SELECT * FROM {table} "
            f"WHERE dataproduct_type = 'image' AND calib_level >= 3 "
            f"AND CONTAINS(POINT('ICRS', {ra}, {dec}), s_region) = 1"
        )
        res = svc.run_sync(adql, maxrec=20000).to_table()
    except Exception as e:
        print(f"  FAILED: {type(e).__name__}: {str(e)[:400]}")
        continue
    print(f"  {len(res)} rows")
    print("  Columns:", ", ".join(res.colnames))
    groups = Counter((str(r["obs_collection"]), str(r["instrument_name"])) for r in res)
    for (coll, inst), n in groups.most_common(30):
        rows = res[(res["obs_collection"] == coll) & (res["instrument_name"] == inst)]
        extra = ""
        for col in ("filter", "energy_bandpassname", "band_name"):
            if col in res.colnames:
                vals = sorted({str(v) for v in rows[col]})
                extra = f"  {col}: {', '.join(vals[:12])}{' ...' if len(vals) > 12 else ''}"
                break
        print(f"  {coll:22} {inst:22} {n:5}{extra}")
    for col in ("data_rights", "obs_release_date", "access_format", "access_estsize", "access_url", "dataproduct_subtype"):
        if col in res.colnames:
            print(f"  {col} sample: {[str(v)[:90] for v in res[col][:3]]}")
