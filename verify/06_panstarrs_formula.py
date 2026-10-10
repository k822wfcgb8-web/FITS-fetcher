"""Verification 06: confirm the Pan-STARRS linearisation formula (REQ-36).

Compares the full stack file (asinh-encoded, downloaded once to verify/downloads/ps1_full_r.fits, 68 MB)
linearised with  flux = BOFFSET + BSOFTEN * 2 * sinh(x / (2.5 / ln 10))  against the PS1 cutout
service's output for the same sky pixels (verify/downloads/ps1_stack.fits from script 05).
"""
import numpy as np
from astropy.io import fits
from astropy.wcs import WCS

full = fits.open("verify/downloads/ps1_full_r.fits")[1]
h = full.header
raw = full.data.astype(np.float64)  # astropy has already applied BSCALE/BZERO
a = 2.5 / np.log(10)
lin = h["BOFFSET"] + h["BSOFTEN"] * 2 * np.sinh(raw / a)

cut = fits.open("verify/downloads/ps1_stack.fits")[0]
yy, xx = np.mgrid[0:cut.data.shape[0], 0:cut.data.shape[1]]
fx, fy = WCS(h).world_to_pixel(WCS(cut.header).pixel_to_world(xx, yy))
sample = lin[np.round(fy).astype(int), np.round(fx).astype(int)]
c = cut.data.astype(np.float64)
ok = np.isfinite(sample) & np.isfinite(c) & (np.abs(c) > 1)
ratio = sample[ok] / c[ok]
print("pixels compared:", ok.sum())
print("ratio full/cutout: median %.6f, 1st-99th percentile %.6f .. %.6f" % (np.median(ratio), *np.percentile(ratio, [1, 99])))
print("raw encoded range: %.3f .. %.3f" % (np.nanmin(raw), np.nanmax(raw)))
print("blank (NaN) pixels in full image: %d of %d" % (np.isnan(raw).sum(), raw.size))
