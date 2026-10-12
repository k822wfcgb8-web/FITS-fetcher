"""Verification 19b: the IRSA download chain on real files for M51 (REQ-85, REQ-86), without the SIA search, which
answered 503 on the morning of 2026-10-12. Products are built from the files found by browsing IRSA's file server:
AllWISE tile 2029p469_ac51 (W1-W4) and 2MASS image 980527n s024 0240232 (J, H, Ks).
Checks: every band of a tile gets the same box (same NAXIS, CRPIX, CRVAL), the object is at the box centre, the
2MASS box is clipped at the 8.5' x 17' image edge with a warning, the compatibility check passes, siril-cli loads it.
Run: .venv/bin/python verify/19b_irsa_download.py
"""
import shutil
import subprocess
import sys
import time
from pathlib import Path

from astropy.table import Table
from astropy.wcs import WCS

sys.path.insert(0, "src")
from fits_fetcher.archives import irsa  # noqa: E402
from fits_fetcher.archives.base import Target  # noqa: E402
from fits_fetcher.config import Settings  # noqa: E402
from fits_fetcher.processing import Options, check_compatible, process, save  # noqa: E402
from fits_fetcher.transfer import Transfer  # noqa: E402

OUT = Path("verify/downloads/19b")
SIRIL = "/Applications/Siril.app/Contents/MacOS/siril-cli"
shutil.rmtree(OUT, ignore_errors=True)
M51 = Target(query="M51", matched_id="M 51", ra=202.469575, dec=47.19525833, size_arcmin=11.2)
WISE = "https://irsa.ipac.caltech.edu/ibe/data/wise/allwise/p3am_cdd/20/2029/2029p469_ac51/2029p469_ac51-{}-int-3.fits"
TWOMASS = "https://irsa.ipac.caltech.edu/ibe/data/twomass/allsky/allsky/980527n/s024/image/{}i0240232.fits.gz"
COVERS = "POLYGON 202.2 46.9 202.8 46.9 202.8 47.5 202.2 47.5"
rows = [("wise_allwise", b.upper(), WISE.format(b)) for b in ("w1", "w2", "w3", "w4")] + \
       [("twomass_allsky", b.upper(), TWOMASS.format(b)) for b in ("j", "h", "k")]
table = Table(rows=[[c, "science", b, u.rsplit("/", 1)[-1], u, COVERS, M51.ra, M51.dec, None, None, 51000.0, None,
                     4095 if c == "wise_allwise" else 512, 4095 if c == "wise_allwise" else 1024] for c, b, u in rows],
              names=["obs_collection", "dataproduct_subtype", "energy_bandpassname", "obs_id", "access_url", "s_region",
                     "s_ra", "s_dec", "em_min", "em_max", "t_min", "t_exptime", "s_xel1", "s_xel2"])

archive = irsa.IrsaArchive(Settings())
transfer = Transfer(OUT / "cache")
ok = True
for r in table:
    p = archive._product(r, M51)
    t0 = time.time()
    f = archive.fetch(p, M51, transfer, 2.0, lambda d, n: None)
    fetched = sum(x.stat().st_size for x in f.files)
    res = process(f, p, M51, Options().for_product(p))
    path = OUT / p.collection / f"{p.filter}.fits"
    save(res, path)
    for x in f.files:
        x.unlink(missing_ok=True)
    h = res.header
    x, y = WCS(h).all_world2pix([[M51.ra, M51.dec]], 0)[0]
    problems = check_compatible(path)
    line = (f"{p.collection:15} {p.filter:3} est {p.width}x{p.height}, got {res.data.shape[1]}x{res.data.shape[0]} px, "
            f"fetched {fetched / 1e6:.2f} MB in {time.time() - t0:.1f} s, CRPIX {h['CRPIX1']:.1f} {h['CRPIX2']:.1f}, "
            f"object at ({x:.1f}, {y:.1f}), grid {p.grid!r}, warnings {res.warnings}, check {problems or 'ok'}")
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
print("ALL OK" if ok else "PROBLEMS")
