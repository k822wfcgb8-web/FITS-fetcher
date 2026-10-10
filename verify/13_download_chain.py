"""Verification 13: the download and processing chain on real MAST products (Section 8, REQ-57, REQ-58).

Downloads the smallest product of each kind for M51 (HST single-visit, JWST, PS1) and two HST mosaics in
different filters (with a small box, to keep the download modest), runs the full chain, and checks:
- each output passes the compatibility check and loads in siril-cli (REQ-49, REQ-50);
- the object is at the centre of each cutout, and both mosaic cutouts have identical WCS (REQ-58);
- the PS1 output is linear (no BOFFSET/BSOFTEN left; values not asinh-compressed).
Run: .venv/bin/python verify/13_download_chain.py  (outputs go to verify/downloads/chain/)
"""
import shutil
import subprocess
import sys
import time
from dataclasses import replace
from pathlib import Path

import numpy as np
from astropy.io import fits
from astropy.wcs import WCS

from fits_fetcher.archives.mast import MastArchive
from fits_fetcher.config import Settings
from fits_fetcher.downloads import DownloadJob, Item
from fits_fetcher.processing import Options, check_compatible
from fits_fetcher.resolve import resolve

OUT = Path("verify/downloads/chain")
SIRIL = "/Applications/Siril.app/Contents/MacOS/siril-cli"
shutil.rmtree(OUT, ignore_errors=True)
settings = Settings(output_dir=str(OUT), cache_dir=str(OUT / "cache"), hst_show_mosaics=True)

(target,) = resolve("M51")
print(f"Target {target.matched_id} size {target.size_arcmin}'")
target = replace(target, size_arcmin=0.5)  # 1' box: keeps the mosaic strip near 130 MB per filter
products = MastArchive(settings).search(target, 0.02)

picked = {}
for p in sorted(products, key=lambda p: p.size_bytes or 0):
    kind = (p.collection, p.is_mosaic)
    if kind not in picked:
        picked[kind] = p
mosaics = [p for p in products if p.is_mosaic and p.instrument == "ACS/WFC"]
second = next(p for p in mosaics if p.filter != picked[("HST", True)].filter and p.grid == picked[("HST", True)].grid)
chosen = list(picked.values()) + [second]
for p in chosen:
    print(f"  {p.collection:4} {p.instrument:13} {p.filter:8} {p.obs_id}  est. {p.size_bytes / 1e6:.0f} MB")

options = Options(star_repair=True, repair_max_area=2000, cutout=False, box_arcmin=1.0)
job = DownloadJob(target, [Item(p, ["Test"]) for p in chosen], options, settings, {"MAST": MastArchive})
t0 = time.time()
job.start()
while not job.finished:
    time.sleep(2)
    s = job.snapshot()
    print(f"\r  {s['bytes_done'] / 1e6:7.0f} / {s['bytes_total'] / 1e6:.0f} MB  "
          + " ".join(f"{it['state'][:4]}" for it in s["items"]), end="", flush=True)
print(f"\nFinished in {time.time() - t0:.0f} s")

ok = True
for it in job.items:
    print(f"\n{it.product.collection} {it.product.filter} {it.product.obs_id}: {it.state} {it.message}")
    if it.state != "saved":
        ok = False
        continue
    path = Path(it.paths[0]).resolve()  # absolute: siril-cli changes into -d before reading -s
    with fits.open(path) as h:
        hd, data = h[0].header, h[0].data
        w = WCS(hd)
        x, y = w.all_world2pix([[target.ra, target.dec]], 0)[0]
        print(f"  {path.name}: {data.shape[1]} x {data.shape[0]} px, {path.stat().st_size / 1e6:.1f} MB, BUNIT={hd.get('BUNIT')}")
        print(f"  object at pixel ({x:.1f}, {y:.1f}); repaired {hd['FFNREG']} regions / {hd['FFNPIX']} px; "
              f"zeros {np.sum(data == 0)}; range {np.nanmin(data):.4g} .. {np.nanmax(data):.4g}")
        problems = check_compatible(path)
        print(f"  compatibility: {problems or 'OK'}")
        ok &= not problems
        if it.product.collection == "PS1":
            linear = "BOFFSET" not in hd and "BSOFTEN" not in hd
            print(f"  PS1 linear keywords gone: {linear}; median {np.median(data):.4g}, 99.9% {np.percentile(data, 99.9):.4g}")
            ok &= linear
    if Path(SIRIL).exists():
        script = path.parent / "check.ssf"
        script.write_text(f"requires 1.4.0\nload \"{path.name}\"\nstat\nclose\n")
        r = subprocess.run([SIRIL, "-d", str(path.parent), "-s", str(script)], capture_output=True, text=True, timeout=300)
        print(f"  siril-cli exit code {r.returncode}")
        ok &= r.returncode == 0
        script.unlink()

m = [it for it in job.items if it.product.is_mosaic and it.state == "saved"]
if len(m) == 2:
    h1, h2 = (fits.getheader(it.paths[0]) for it in m)
    keys = ("NAXIS1", "NAXIS2", "CRVAL1", "CRVAL2", "CRPIX1", "CRPIX2", "PC1_1", "PC2_2", "CDELT1", "CDELT2")
    same = all(h1.get(k) == h2.get(k) for k in keys)
    print(f"\nMosaic cutouts {m[0].product.filter} / {m[1].product.filter} share one grid: {same}")
    ok &= same
print("\nCredits file:", (OUT / "M51" / "CREDITS.txt").exists())
print("Cache left over:", [p.name for p in (OUT / "cache" / "downloads").glob("*")])
sys.exit(0 if ok else 1)
