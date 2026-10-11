"""Verification 17: mostly blank images and trimming (REQ-75, REQ-76), NGC 3675 WFPC2.

The F336W and F450W single-visit images of visit 11128_09 opened grey in PixInsight. This script downloads both
through the full chain in two separate downloads (grid footprints filled in as the web app does), and for
each output prints:
- shape, blank share and FFBLANK, and whether both filters still share one pixel grid (same CRPIX/CRVAL, shape);
- the Auto Stretch (STF) parameters PixInsight would compute, before and after trimming: with more than half the
  pixels at exactly 0, the median and the spread (MAD) are both 0 and every pixel above 0 turns white.
Run: .venv/bin/python verify/17_blank_borders.py  (outputs go to verify/downloads/blank/)
"""
import shutil
import subprocess
import time
from dataclasses import replace
from pathlib import Path

import numpy as np
from astropy.io import fits

from fits_fetcher.archives.mast import MastArchive
from fits_fetcher.config import Settings
from fits_fetcher.downloads import DownloadJob, Item
from fits_fetcher.processing import Options, check_compatible
from fits_fetcher.resolve import resolve

OUT = Path("verify/downloads/blank")
SIRIL = "/Applications/Siril.app/Contents/MacOS/siril-cli"
shutil.rmtree(OUT, ignore_errors=True)
settings = Settings(output_dir=str(OUT), cache_dir=str(OUT / "cache"))


def stf(data: np.ndarray) -> str:
    """PixInsight's Auto Stretch defaults (shadows -2.8 MAD, target background 0.25) on [0, 1]-rescaled data."""
    x = (data - data.min()) / (data.max() - data.min())
    s = x.ravel()[::7]
    med = float(np.median(s))
    mad = 1.4826 * float(np.median(np.abs(s - med)))
    c0 = max(0.0, med - 2.8 * mad)
    d = med - c0
    m = 0.0 if d <= 0 else (0.25 - 1) * d / ((2 * 0.25 - 1) * d - 0.25)  # midtones balance putting d at 0.25
    return f"median {med:.6f}, MAD {mad:.2e}, midtones {m:.2e}" + ("  ← fails: all above 0 goes white" if mad == 0 else "")


(target,) = resolve("NGC 3675")
products = MastArchive(settings).search(target, 0.02)
grid = {p.obs_id: p for p in products if p.instrument.startswith("WFPC2") and "11128_09" in p.obs_id}
chosen = [p for p in grid.values() if p.filter in ("F336W", "F450W")]
regions = sorted({q.region for q in products if q.grid == chosen[0].grid and q.region})
chosen = [replace(p, grid_regions=regions) for p in chosen]
print(f"{target.matched_id}: {len(chosen)} images on grid '{chosen[0].grid}', {len(regions)} footprints")

# One download per filter, as if on different days: the second must find the first's box in the saved file.
items = []
for p in chosen:
    job = DownloadJob(target, [Item(p, ["Test"])], Options(), settings, {"MAST": MastArchive})
    t0 = time.time()
    job.start()
    while not job.finished:
        time.sleep(1)
    print(f"{p.filter} downloaded and processed in {time.time() - t0:.0f} s")
    items += job.items

heads = []
for it in items:
    print(f"\n{it.product.filter}: {it.state}  {it.message}")
    path = Path(it.paths[0]).resolve()  # absolute: siril-cli changes into -d before reading -s
    with fits.open(path) as h:
        data, head = h[0].data, h[0].header
    heads.append(head)
    blank = np.mean(data == 0)
    print(f"  {data.shape[1]} x {data.shape[0]} px, {blank:.0%} blank, FFBLANK {head['FFBLANK']}, FFTRIM {head['FFTRIM']}")
    print(f"  STF after trimming: {stf(data.astype(np.float64))}")
    print("  " + "\n  ".join(str(c) for c in head["HISTORY"] if "Trim" in str(c) or "blank" in str(c)))
    print(f"  compatibility: {check_compatible(path) or 'ok'}")
    if Path(SIRIL).exists():
        script = path.parent / "check.ssf"
        script.write_text(f"requires 1.4.0\nload \"{path.name}\"\nstat\nclose\n")
        r = subprocess.run([SIRIL, "-d", str(path.parent), "-s", str(script)], capture_output=True, text=True)
        print(f"  siril-cli exit {r.returncode}")

same = all(heads[0][k] == h[k] for h in heads[1:] for k in ("NAXIS1", "NAXIS2", "CRPIX1", "CRPIX2", "CRVAL1", "CRVAL2"))
print(f"\nSame pixel grid after trimming: {same}")
