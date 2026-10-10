"""Verification 05: Pan-STARRS stack pixel encoding (REQ-36).

Fetches a small 240x240 cutout of the M51 r-band stack (a few hundred KB) from the PS1 image service
and prints the scaling keywords. Run: .venv/bin/python verify/05_panstarrs_encoding.py
"""
import io

import numpy as np
import requests
from astropy.coordinates import SkyCoord
from astropy.io import fits

c = SkyCoord.from_name("M51")
lst = requests.get("https://ps1images.stsci.edu/cgi-bin/ps1filenames.py",
                   params={"ra": c.ra.deg, "dec": c.dec.deg, "filters": "r", "type": "stack,stack.mask,stack.wt"}, timeout=60).text
print(lst)
rows = [l.split() for l in lst.strip().splitlines()[1:]]
for row in rows:
    kind, fname = row[6], row[7]  # columns: projcell subcell ra dec filter mjd type filename shortname badflag
    url = "https://ps1images.stsci.edu/cgi-bin/fitscut.cgi"
    r = requests.get(url, params={"red": fname, "format": "fits", "ra": c.ra.deg, "dec": c.dec.deg, "size": 240}, timeout=120)
    hdul = fits.open(io.BytesIO(r.content))
    h = hdul[0].header
    d = hdul[0].data
    print(f"\n--- {fname} ({len(r.content)} bytes) ---")
    for k in ("BITPIX", "BSCALE", "BZERO", "BOFFSET", "BSOFTEN", "BLANK", "EXPTIME", "ZPT_OBS", "FPA.ZP", "HIERARCH FPA.ZP", "BUNIT"):
        if k in h:
            print(f"  {k:10} = {h[k]}")
    print("  data dtype:", d.dtype, " min/median/max:", np.nanmin(d), np.nanmedian(d), np.nanmax(d), " NaNs:", int(np.isnan(d).sum()) if d.dtype.kind == "f" else "-")
    if "BSOFTEN" in h and "BOFFSET" in h:
        a = 2.5 / np.log(10)
        lin = h["BOFFSET"] + h["BSOFTEN"] * 2 * np.sinh(d / a)
        print("  linearised (BOFFSET + BSOFTEN*2*sinh(x/a)) min/median/max:", np.nanmin(lin), np.nanmedian(lin), np.nanmax(lin))
    fits.writeto(f"verify/downloads/ps1_{kind}.fits", d, h, overwrite=True)
