"""Verification 18: planets and moons (REQ-78 to REQ-81), Saturn, 2026-10-11.

'saturn' used to resolve only to the Saturn Nebula (NGC 7009). Checks, against live SIMBAD and MAST:
- 'saturn' lists the planet first and the Saturn Nebula after it;
- the name search finds the JWST visits of programme 1247 (the June 2023 NIRCam image processed by J. DePasquale)
  and Hubble visits, one colour set per visit;
- one JWST and one Hubble single-exposure set download, process uncut, pass the compatibility check and load
  in siril-cli.
Run: .venv/bin/python verify/18_planets.py  (outputs go to verify/downloads/planets/)
"""
import shutil
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
from astropy.io import fits

from fits_fetcher.archives.mast import MastArchive
from fits_fetcher.config import Settings
from fits_fetcher.downloads import DownloadJob, Item
from fits_fetcher.grouping import build_sets
from fits_fetcher.processing import Options, check_compatible
from fits_fetcher.resolve import resolve

OUT = Path("verify/downloads/planets")
SIRIL = "/Applications/Siril.app/Contents/MacOS/siril-cli"
shutil.rmtree(OUT, ignore_errors=True)
settings = Settings(output_dir=str(OUT), cache_dir=str(OUT / "cache"))

found = resolve("saturn")
print("Candidates:", [(t.matched_id, t.object_type) for t in found])
saturn = found[0]
assert saturn.body == "Saturn" and any("7009" in t.matched_id or "Saturn" in t.matched_id for t in found[1:])

t0 = time.time()
products = MastArchive(settings).search(saturn, 0.02)
sets = build_sets(products, min_filters=3)
print(f"{len(products)} images, {len(sets)} sets with 3+ filters, {time.time() - t0:.1f} s")
for s in sets[:5]:
    print(f"  {s.name}  {s.date}")
jwst = [s for s in sets if s.visit.startswith("jw01247")]
for s in jwst:
    print(f"  JWST {s.visit} {s.date}: {s.readiness}")
assert len(jwst) == 2

# One JWST set, and three filters (blue, green, red) of the newest Hubble WFC3/UVIS set.
hst = next(s for s in sets if s.instruments == ["WFC3/UVIS"])
rgb = [r for r in hst.rows if r.filter in ("F395N", "F502N", "F631N")]
chosen = [(r.products[0], jwst[0].name) for r in jwst[0].rows] + [(r.products[0], hst.name) for r in rgb]
for p, _ in chosen:
    print(f"  {p.instrument:13} {p.filter:8} {p.obs_id}  {p.product_level}  est. {(p.size_bytes or 0) / 1e6:.0f} MB")

options = Options(star_repair=True, repair_max_area=2000, cutout=True, box_arcmin=1.0)  # cutout must be ignored
job = DownloadJob(saturn, [Item(p, [name]) for p, name in chosen], options, settings, {"MAST": MastArchive})
job.start()
while not job.finished:
    time.sleep(2)
print(f"Downloads finished in {time.time() - t0:.0f} s")

ok = True
for it in job.items:
    print(f"\n{it.product.collection} {it.product.filter} {it.product.obs_id}: {it.state} {it.message}")
    if it.state != "saved":
        ok = False
        continue
    path = Path(it.paths[0]).resolve()  # absolute: siril-cli changes into -d before reading -s
    with fits.open(path) as h:
        hd, data = h[0].header, h[0].data
        print(f"  {path.relative_to(OUT.resolve())}: {data.shape[1]} x {data.shape[0]} px "
              f"(archive image {it.product.width or '?'} wide), BUNIT={hd.get('BUNIT')}, "
              f"repaired {hd['FFNREG']} regions / {hd['FFNPIX']} px, range {np.nanmin(data):.4g} .. {np.nanmax(data):.4g}")
        cut = [str(v) for v in hd.get("HISTORY", []) if str(v).startswith("Cut around")]
        print(f"  cut around object: {cut or 'no'}")
        ok &= not cut
    problems = check_compatible(path)
    print(f"  compatibility: {problems or 'OK'}")
    ok &= not problems
    if Path(SIRIL).exists():
        script = path.parent / "check.ssf"
        script.write_text(f"requires 1.4.0\nload \"{path.name}\"\nstat\nclose\n")
        r = subprocess.run([SIRIL, "-d", str(path.parent), "-s", str(script)], capture_output=True, text=True, timeout=300)
        print(f"  siril-cli exit code {r.returncode}")
        ok &= r.returncode == 0
        script.unlink()
print("\nFolders:", sorted(str(d.relative_to(OUT)) for d in OUT.glob("*/*") if d.is_dir() and "cache" not in d.parts))
sys.exit(0 if ok else 1)
