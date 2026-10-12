"""Verification 19c: the IRSA module end to end once the SIA search was back (2026-10-12 09:52): live search for M51,
then the Spitzer IRAC box (fetched as rows, REQ-85) and MIPS 24 µm, processed, checked and loaded in siril-cli.
Run: .venv/bin/python verify/19c_irsa_live.py
"""
import shutil
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

from astropy.wcs import WCS

sys.path.insert(0, "src")
from fits_fetcher.archives import irsa  # noqa: E402
from fits_fetcher.archives.base import Target  # noqa: E402
from fits_fetcher.config import Settings  # noqa: E402
from fits_fetcher.processing import Options, check_compatible, process, save  # noqa: E402
from fits_fetcher.transfer import Transfer  # noqa: E402

OUT = Path("verify/downloads/19c")
SIRIL = "/Applications/Siril.app/Contents/MacOS/siril-cli"
shutil.rmtree(OUT, ignore_errors=True)
M51 = Target(query="M51", matched_id="M 51", ra=202.469575, dec=47.19525833, size_arcmin=11.2)
archive = irsa.IrsaArchive(Settings())
t0 = time.time()
found = archive.search(M51, 0.02)
print(f"search {time.time() - t0:.1f} s: {len(found)} images,", dict(Counter((p.collection, p.filter) for p in found)))
assert len({p.key for p in found}) == len(found), "duplicate keys"
spitzer = [p for p in found if p.collection == "spitzer_seip" and not p.chip]
transfer = Transfer(OUT / "cache")
ok = True
for p in sorted(spitzer, key=lambda p: p.filter):
    t0 = time.time()
    f = archive.fetch(p, M51, transfer, 2.0, lambda d, n: None)
    fetched = sum(x.stat().st_size for x in f.files)
    res = process(f, p, M51, Options().for_product(p))
    path = OUT / f"{p.filter}.fits"
    save(res, path)
    for x in f.files:
        x.unlink(missing_ok=True)
    h = res.header
    x, y = WCS(h).all_world2pix([[M51.ra, M51.dec]], 0)[0]
    problems = check_compatible(path)
    ok &= not problems
    line = (f"{p.filter:6} est {p.size_bytes / 1e6:.1f} MB, fetched {fetched / 1e6:.1f} MB in {time.time() - t0:.1f} s, "
            f"{res.data.shape[1]}x{res.data.shape[0]} px, CRPIX {h['CRPIX1']:.2f} {h['CRPIX2']:.2f}, object at "
            f"({x:.1f}, {y:.1f}), EXPTIME {h.get('EXPTIME')}, BUNIT {h.get('BUNIT')}, warnings {res.warnings}, "
            f"check {problems or 'ok'}")
    if Path(SIRIL).exists():
        script = path.parent / "check.ssf"
        script.write_text(f"requires 1.4.0\nload \"{path.name}\"\nstat\nclose\n")
        s = subprocess.run([SIRIL, "-d", str(path.parent.resolve()), "-s", str(script.resolve())],
                           capture_output=True, text=True, timeout=300)
        line += f", siril-cli exit {s.returncode}"
        ok &= s.returncode == 0
        script.unlink()
    print(line)
print("ALL OK" if ok else "PROBLEMS")
