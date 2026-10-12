"""Verification 21: CADC collections and mirrors (REQ-21, REQ-35), 2026-10-12.

CADC was unreachable from the home network (Fidium) since 2026-10-10; this run was made over a phone
hotspot (Verizon). Checks, against live CADC TAP (argus ObsCore):
- which collections hold images, at which calib levels, and which mirror MAST/ESO/IRSA holdings;
- what CADC returns for a set of test objects once mirrors are excluded;
- which stacked products exist around M51, NGC 891 and M87, and whether a small cutout comes back on the
  original pixel grid. The run on 2026-10-12 was made in pieces (weak connection); see FINDINGS.md step 21.
Run: .venv/bin/python verify/21_cadc.py
"""
import time
from collections import Counter

import pyvo
from astropy.coordinates import SkyCoord

TAP = "https://ws.cadc-ccda.hia-iha.nrc-cnrc.gc.ca/argus"
cadc = pyvo.dal.TAPService(TAP)

for name in ["M51", "M42", "NGC 7293", "M31", "M1", "NGC 891"]:
    c = SkyCoord.from_name(name)
    q = (f"SELECT obs_collection, instrument_name, calib_level, facility_name, COUNT(*) AS n FROM ivoa.ObsCore "
         f"WHERE dataproduct_type = 'image' AND CONTAINS(POINT('ICRS', {c.ra.deg}, {c.dec.deg}), s_region) = 1 "
         f"GROUP BY obs_collection, instrument_name, calib_level, facility_name")
    t0 = time.time()
    t = cadc.run_sync(q, maxrec=10000).to_table()
    print(f"\n== {name}: {sum(int(r['n']) for r in t)} image rows ({time.time() - t0:.1f} s) ==")
    for r in sorted(t, key=lambda r: -int(r["n"])):
        print(f"  {r['obs_collection']!s:14} {r['instrument_name']!s:22} L{r['calib_level']} "
              f"{r['facility_name']!s:12} n={r['n']}")

print("\n== Image collections (whole archive, CADC's precomputed counts in caom2.ObsCoreEnumField) ==")
t = cadc.run_sync("SELECT obs_collection, facility_name, instrument_name, calib_level, num_tuples FROM caom2.ObsCoreEnumField "
                  "WHERE dataproduct_type = 'image'", maxrec=100000).to_table()
by = {}
for r in t:
    key = (str(r["obs_collection"]), str(r["facility_name"]))
    lv = by.setdefault(key, {})
    lv[int(r["calib_level"])] = lv.get(int(r["calib_level"]), 0) + int(r["num_tuples"])
for (coll, fac) in sorted(by, key=lambda k: -sum(by[k].values())):
    print(f"  {coll:16} {fac:18} " + "  ".join(f"L{k}={v}" for k, v in sorted(by[(coll, fac)].items())))

# Stacked products only (the collections that aren't mirrors, raw frames or radio), with filters and sizes.
STACKS = "('CFHTMEGAPIPE','CFHTWIRWOLF','CFHTTERAPIX','NGVS','SUBARUCADC','LSST.DP1','EUCLID.DR1','EUCLID.Q1','DAOCADC')"
for name in ["M51", "NGC 891", "M87"]:
    c = SkyCoord.from_name(name)
    t = cadc.run_sync(
        f"SELECT o.collection, o.observationID, p.productID, p.calibrationLevel, p.energy_bandpassName, p.time_exposure, "
        f"p.position_sampleSize, p.position_dimension_naxis1, p.position_dimension_naxis2, p.dataRelease "
        f"FROM caom2.Plane p JOIN caom2.Observation o ON p.obsID = o.obsID "
        f"WHERE o.collection IN {STACKS} AND p.dataProductType = 'image' "
        f"AND CONTAINS(POINT('ICRS', {c.ra.deg}, {c.dec.deg}), p.position_bounds) = 1", maxrec=2000).to_table()
    print(f"\n== {name}: stacked products by collection, level and filter ==")
    for (coll, lv, band), n in sorted(Counter((str(r["collection"]), int(r["calibrationLevel"]), str(r["energy_bandpassName"]))
                                              for r in t).items()):
        print(f"  {coll:14} L{lv} {band:12} n={n}")

# A 55 x 55 px cutout (20 KB) of one MegaPipe g tile at M51's centre, through CADC's file locator. Capped at 2 MB:
# a locator that answers with the file itself instead of a redirect must not pull 400 MB.
import requests
from astropy.io import fits
from io import BytesIO
URL = "https://ws.cadc-ccda.hia-iha.nrc-cnrc.gc.ca/raven/files/cadc:CFHTSG/MegaPipe.276.274.G.MP9401.fits"
with requests.get(URL, params={"SUB": "[0][3353:3407,8758:8812]"}, stream=True, timeout=60) as r:
    body = b""
    for chunk in r.iter_content(65536):
        body += chunk
        if len(body) > 2_000_000:
            raise SystemExit("cutout over 2 MB, stopped")
print(f"\n== Cutout: {r.status_code}, {len(body)} B, via {[h.url.split('/')[2] for h in r.history] + [r.url.split('/')[2]]}")
if body[:6] == b"SIMPLE":
    hd = fits.getheader(BytesIO(body))
    print("  ", {k: hd.get(k) for k in ["NAXIS1", "NAXIS2", "CRPIX1", "CRPIX2", "FILTER", "EXPTIME", "PHOTZP"]})
else:
    print("  ", body[:120])
