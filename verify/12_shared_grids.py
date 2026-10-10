"""Verification 12: which images share one pixel grid and stack without registration (REQ-60)?

Reads only the science-extension headers (over HTTP, no full download) and compares the grid keywords of
  - HST single-visit (HAP) images from the same visit vs. different visits (M1, WFC3/UVIS, proposal 17500)
  - Pan-STARRS stacks in the same skycell vs. a neighbouring skycell (M1 and M51)
Run: .venv/bin/python verify/12_shared_grids.py
"""
import warnings

from astropy.io import fits

from fits_fetcher.archives.mast import file_url

warnings.simplefilter("ignore")
GRID = ["NAXIS1", "NAXIS2", "CRVAL1", "CRVAL2", "CRPIX1", "CRPIX2"]

HST = ["hst_17500_06_wfc3_uvis_f502n_if8506", "hst_17500_06_wfc3_uvis_f631n_if8506",
       "hst_17500_06_wfc3_uvis_f673n_if8506", "hst_17500_04_wfc3_uvis_f502n_if8504",
       "hst_17500_04_wfc3_uvis_f631n_if8504", "hst_17500_08_wfc3_uvis_f487n_if8508"]
PS1 = [f"rings.v3.skycell.1784.059.stk.{b}" for b in "grizy"] + \
      [f"rings.v3.skycell.2261.075.stk.{b}" for b in "gr"] + ["rings.v3.skycell.2261.085.stk.g"]


def grid(url, ext):
    with fits.open(url, use_fsspec=True, lazy_load_hdus=True) as h:
        hd = h[ext].header
        return tuple(round(hd[k], 6) if isinstance(hd[k], float) else hd[k] for k in GRID)


for obs_id in HST:
    print(f"{obs_id:40s}", grid(file_url("HST", "WFC3/UVIS", obs_id), "SCI"))
for obs_id in PS1:
    print(f"{obs_id:40s}", grid(file_url("PS1", "GPC1", obs_id), 1))
