"""Verification 10: can siril-cli be scripted to load test outputs (REQ-50)?

Builds four small files from the PS1 cutout (verify/downloads/ps1_stack.fits, from script 05):
  good.fits        - single HDU, BITPIX -32, no scaling, no compression (REQ-46/47, the app's output format)
  multi_hdu.fits   - empty primary + image in extension 1 (like HST/JWST originals)
  scaled.fits      - 16-bit integers with BSCALE/BZERO
  compressed.fits  - Rice tile-compressed image extension
then loads each in its own siril-cli script and reports what Siril says.
Run: .venv/bin/python verify/10_siril_cli.py
"""
import pathlib
import subprocess

import numpy as np
from astropy.io import fits

SIRIL = "/Applications/Siril.app/Contents/MacOS/siril-cli"
work = pathlib.Path("verify/downloads/siril").resolve()
work.mkdir(parents=True, exist_ok=True)

src = fits.open("verify/downloads/ps1_stack.fits")[0]
data = src.data.astype(np.float32)
hdr = src.header.copy()
for k in ("BSCALE", "BZERO", "BLANK"):
    hdr.remove(k, ignore_missing=True)

fits.PrimaryHDU(data, hdr).writeto(work / "good.fits", overwrite=True)
fits.HDUList([fits.PrimaryHDU(), fits.ImageHDU(data, hdr, name="SCI")]).writeto(work / "multi_hdu.fits", overwrite=True)
scaled = fits.PrimaryHDU(data.copy(), hdr)
scaled.scale("int16", bscale=float((data.max() - data.min()) / 60000), bzero=float((data.max() + data.min()) / 2))
scaled.writeto(work / "scaled.fits", overwrite=True)
fits.HDUList([fits.PrimaryHDU(), fits.CompImageHDU(data, hdr, compression_type="RICE_1")]).writeto(work / "compressed.fits", overwrite=True)

for name in ["good", "multi_hdu", "scaled", "compressed"]:
    script = work / f"load_{name}.ssf"
    script.write_text(f"requires 1.4.0\nload {name}.fits\nstat\nclose\n")
    p = subprocess.run([SIRIL, "-d", str(work), "-s", str(script)], capture_output=True, text=True, timeout=120)
    out = [l for l in (p.stdout + p.stderr).splitlines()
           if any(w in l.lower() for w in ("error", "fail", "loaded", "reading", "mean", "median", "not", "unsupported", "cannot", "bits", "channel", "wcs", "astrometric"))]
    print(f"\n=== {name}.fits  exit={p.returncode} ===")
    for l in out[:12]:
        print("  ", l[:170])
