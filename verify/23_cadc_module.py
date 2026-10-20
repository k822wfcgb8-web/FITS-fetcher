"""Verification 23: details for building the CADC module (REQ-95 to REQ-99), 2026-10-20, over Fidium.

Checks, against live CADC:
- the registry entries the module uses (argus TAP, global raven file locator);
- whether the filters of one tile share a pixel grid (headers only, via one range request each), for MegaPipe's
  2020 and 2012-15 tiles, Suprime-Cam stacks and WIRWOLF stacks;
- a CIRCLE cutout (box on the file's own grid) and a thinned SUB cutout for thumbnails.
Run: .venv/bin/python verify/23_cadc_module.py
"""
import time, requests
from io import BytesIO
from astropy.io import fits
caps = requests.get("https://ws.cadc-ccda.hia-iha.nrc-cnrc.gc.ca/reg/resource-caps", timeout=30).text
for line in caps.splitlines():
    if any(k in line for k in ("argus", "global/raven", "caom2ops", "/minoc", "/data ")):
        print("REG", line)
RAVEN = "https://ws.cadc-ccda.hia-iha.nrc-cnrc.gc.ca/raven/files/"
def get(url, params=None, headers=None, cap=3_000_000):
    t0 = time.time()
    with requests.get(url, params=params, headers=headers or {}, stream=True, timeout=60) as r:
        body = b""
        for ch in r.iter_content(65536):
            body += ch
            if len(body) > cap: break
    hops = [h.status_code for h in r.history]
    print(f"  {r.status_code} hops={hops} {len(body)} B {time.time()-t0:.1f}s {r.url[:140]}")
    return r, body
def hdr(body):
    try:
        h = fits.getheader(BytesIO(body))
        return {k: h.get(k) for k in ["NAXIS1","NAXIS2","CRPIX1","CRPIX2","CRVAL1","CRVAL2","CD1_1","CD2_2","CTYPE1","FILTER","EXPTIME","PHOTZP","BUNIT","BITPIX"]}
    except Exception as e:
        return f"not fits: {body[:100]!r} {e}"
f = "cadc:CFHTSG/MegaPipe.276.274.G.MP9401.fits"
print("CIRCLE"); r, b = get(RAVEN + f, {"CIRCLE": "202.4696 47.1953 0.01"}); print("  ", hdr(b))
print("SUB"); r, b = get(RAVEN + f, {"SUB": "[0][3353:3407,8758:8812]"}); print("  ", hdr(b))
print("THIN"); r, b = get(RAVEN + f, {"SUB": "[0][2000:5000:15,7000:10000:15]"}); print("  ", hdr(b))
print("HEADER RANGE"); r, b = get(RAVEN + f, headers={"Range": "bytes=0-28799"}); print("  ", hdr(b))
for f in ["cadc:CFHTSG/MegaPipe.053.265.G.MP9401.fits","cadc:CFHTSG/MegaPipe.053.265.R.MP9601.fits","cadc:CFHTSG/MegaPipe.053.265.Z.MP9801.fits",
          "cadc:SUBARUCADC/SCLA.053.265.W-J-V.fits","cadc:SUBARUCADC/SCLA.053.265.W-S-G+.fits",
          "cadc:CFHTSG/G011.035.638+42.345.G.fits","cadc:CFHTSG/G011.035.638+42.345.R.fits",
          "cadc:CFHTSG/GW001.035.637+42.346.J.fits","cadc:CFHTSG/GW001.035.637+42.346.K.fits",
          "cadc:SUBARUCADC/SCLA_035.556+42.350.W-J-V.fits","cadc:SUBARUCADC/SCLA_035.556+42.350.W-S-G.fits"]:
    print(f); r, b = get(RAVEN + f, headers={"Range": "bytes=0-28799"}); print("  ", hdr(b))
