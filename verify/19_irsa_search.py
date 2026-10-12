"""Verification 19: what an IRSA search returns for the three pipeline collections (REQ-56), before building the
IRSA module. Per object and collection: query time, science rows, rows whose footprint contains the centre (REQ-14),
products per band (REQ-53), pixel grids shared across bands (REQ-60), sizes, and how much of the object one image
covers. Run: .venv/bin/python verify/19_irsa_search.py
"""
import sys
import time
from collections import Counter, defaultdict

import astropy.units as u
from astropy.coordinates import SkyCoord
from astroquery.ipac.irsa import Irsa

sys.path.insert(0, "src")
from fits_fetcher import footprint  # noqa: E402

OBJECTS = {"M51": 11.2, "M42": 65.0, "NGC 7293": 25.0, "M1": 7.0, "NGC 1300": 6.2}
COLLS = ["spitzer_seip", "wise_allwise", "twomass_allsky"]

first = True
for name, size in OBJECTS.items():
    c = SkyCoord.from_name(name)
    print(f"\n######## {name}  ({c.ra.deg:.4f}, {c.dec.deg:+.4f})  size {size}'")
    for coll in COLLS:
        t0 = time.time()
        try:
            t = Irsa.query_sia(pos=(c, 0.02 * u.deg), collection=coll)
        except Exception as e:
            print(f"  {coll}: FAILED {type(e).__name__}: {str(e)[:120]}")
            continue
        dt = time.time() - t0
        if first:
            print("  columns:", t.colnames)
            first = False
        sci = t[t["dataproduct_subtype"] == "science"]
        cen = [r for r in sci if footprint.contains(str(r["s_region"]), c.ra.deg, c.dec.deg)]
        bands = Counter(str(r["energy_bandpassname"]) for r in cen)
        print(f"  {coll}: {dt:.1f} s, {len(t)} rows, {len(sci)} science, {len(cen)} contain centre; per band {dict(bands)}")
        grids = defaultdict(list)
        for r in cen:
            key = (str(r["s_xel1"]), str(r["s_xel2"]), round(float(r["s_ra"]), 6), round(float(r["s_dec"]), 6),
                   round(float(r["s_pixel_scale"]) if "s_pixel_scale" in t.colnames else 0, 4))
            grids[key].append(str(r["energy_bandpassname"]))
        for k, v in list(grids.items())[:6]:
            print(f"     grid {k}: {v}")
        for r in cen[:3]:
            cov = footprint.coverage([str(r["s_region"])], c.ra.deg, c.dec.deg, size)
            print(f"     {str(r['energy_bandpassname']):7} {str(r['obs_id'])[:40]:40} size={r['access_estsize']} kB "
                  f"res={r['s_resolution']} t_exp={r['t_exptime']} date={r['t_min']} cover={cov} "
                  f"url=...{str(r['access_url'])[-60:]}")
            print(f"        s_region={str(r['s_region'])[:100]}")
