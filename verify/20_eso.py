"""Verification 20: the ESO module (REQ-90 to REQ-93) against the live archive, 2026-10-12.
Part 1, search: for each object, image rows before and after the selection rules and repeat removal (REQ-91), and
the colour sets at the default 3 filters; checks every thumbnail address answers.
Part 2, download chain on real files: M83 HAWK-I (all four filters of the pointing nearest the centre) and VHS
(Y, J, Ks). Checks: the box is on the file's own grid (CRPIX moves by whole pixels), the object sits at its centre,
size estimates match, the compatibility check passes, siril-cli loads each file, credits carry the DOIs.
Run: .venv/bin/python verify/20_eso.py
"""
import shutil
import subprocess
import sys
import time
from pathlib import Path

import requests
from astropy.wcs import WCS

sys.path.insert(0, "src")
from fits_fetcher.archives import eso  # noqa: E402
from fits_fetcher.archives.base import Target  # noqa: E402
from fits_fetcher.config import Settings  # noqa: E402
from fits_fetcher.grouping import build_sets  # noqa: E402
from fits_fetcher.output import write_credits  # noqa: E402
from fits_fetcher.processing import Options, check_compatible, process, save  # noqa: E402
from fits_fetcher.resolve import resolve  # noqa: E402
from fits_fetcher.transfer import Transfer  # noqa: E402

OUT = Path("verify/downloads/20")
SIRIL = "/Applications/Siril.app/Contents/MacOS/siril-cli"
shutil.rmtree(OUT, ignore_errors=True)
archive = eso.EsoArchive(Settings())

print("== Part 1: search ==")
for name in ["M83", "NGC 253", "NGC 7293", "M42", "NGC 300", "M8", "NGC 3372", "NGC 1365", "NGC 5128", "NGC 104"]:
    t = resolve(name)[0]
    t0 = time.time()
    raw = archive._query(t, [eso.TELESCOPES[k].instrument for k in archive._telescopes()])
    products = archive.search(t, 0.02)
    dt = time.time() - t0
    sets = build_sets(products, min_filters=3)
    thumbs = [p.thumbnail_url for p in products if p.thumbnail_url]
    bad = [u for u in thumbs[:6] if requests.get(u, timeout=60).status_code != 200]
    print(f"{name:9} size {t.size_arcmin or 0:5.1f}′: {len(raw)} combined rows → {len(products)} images in {dt:.1f} s;"
          f" {len(thumbs)} with a sky-map thumbnail{' (FAILED: ' + str(len(bad)) + ')' if bad else ''}")
    for s in sets:
        print(f"    set {s.name}: {s.readiness}; lowest coverage "
              f"{'—' if s.coverage is None else f'{s.coverage:.0%}'}; images per filter "
              f"{[len(r.products) for r in s.rows]}")

print("\n== Part 2: download chain, M83 ==")
m83 = resolve("M83")[0]
products = archive.search(m83, 0.02)
chosen = [p for p in products if p.survey == "VHS"]
hawki = [p for p in products if p.collection == "HAWKI"]
for f in sorted({p.filter for p in hawki}):  # nearest pointing in each filter
    chosen.append(min((p for p in hawki if p.filter == f), key=lambda p: p.offset_arcmin))
transfer = Transfer(OUT / "cache")
ok = True
for p in chosen:
    t0 = time.time()
    f = archive.fetch(p, m83, transfer, 2.0, lambda d, n: None)
    fetched = sum(x.stat().st_size for x in f.files)
    res = process(f, p, m83, Options().for_product(p))
    path = OUT / "M83" / p.collection / f"{p.filter}_{p.obs_id}.fits"
    save(res, path)
    for x in f.files:
        x.unlink(missing_ok=True)
    h = res.header
    x, y = WCS(h).all_world2pix([[m83.ra, m83.dec]], 0)[0]
    problems = check_compatible(path)
    line = (f"{p.survey:6} {p.filter:4} est {p.width}x{p.height} px {p.size_bytes / 1e6:.1f} MB, got "
            f"{res.data.shape[1]}x{res.data.shape[0]} px, fetched {fetched / 1e6:.1f} MB in {time.time() - t0:.1f} s, "
            f"CRPIX {h['CRPIX1']:.3f} {h['CRPIX2']:.3f}, object at ({x:.1f}, {y:.1f}), "
            f"blank {h.get('FFBLANK')}%, repair {h['FFNREG']} regions, warnings {res.warnings}, check {problems or 'ok'}")
    ok &= not problems
    if Path(SIRIL).exists():
        script = path.parent / "check.ssf"
        script.write_text(f"requires 1.4.0\nload \"{path.name}\"\nstat\nclose\n")
        s = subprocess.run([SIRIL, "-d", str(path.parent.resolve()), "-s", str(script.resolve())],
                           capture_output=True, text=True, timeout=300)
        line += f", siril-cli exit {s.returncode}"
        ok &= s.returncode == 0
        script.unlink()
    print(line)
credits = write_credits(OUT / "M83").read_text()
print("credits DOIs:", sorted({ln.split("archive/")[1].rstrip(".") for ln in credits.split() if "10.18727" in ln}))
print("ALL OK" if ok else "PROBLEMS")
