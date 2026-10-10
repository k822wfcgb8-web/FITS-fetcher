"""Verification 07: HDU structure of combined products (REQ-08, S-23, REQ-37).

Reads headers only (HTTP range requests via fsspec), to see which extension is the science image and
whether a data-quality (DQ) array survives in combined products. Run: .venv/bin/python verify/07_hdu_structure.py
"""
import astropy.units as u
import numpy as np
from astropy.coordinates import SkyCoord
from astropy.io import fits
from astroquery.mast import Observations

MAST_DL = "https://mast.stsci.edu/api/v0.1/Download/file?uri="
c = SkyCoord.from_name("M51")
obs = Observations.query_criteria(coordinates=c, radius=0.02 * u.deg, dataproduct_type="image",
                                  calib_level=[3], intentType="science", dataRights="PUBLIC",
                                  obs_collection=["HST", "JWST", "PS1"])
wanted = {"ACS/WFC": "DRC", "WFC3/UVIS": "DRC", "WFC3/IR": "DRZ", "NIRCAM/IMAGE": "I2D", "MIRI/IMAGE": "I2D", "GPC1": None}
seen = set()
for inst, sub in wanted.items():
    rows = obs[obs["instrument_name"] == inst]
    if not len(rows):
        print(f"\n{inst}: no observations"); continue
    prods = Observations.get_product_list(rows[:3])
    prods = prods[(prods["productType"] == "SCIENCE") & (prods["calib_level"] >= 3)]
    if sub:
        prods = prods[prods["productSubGroupDescription"] == sub]
    if not len(prods):
        print(f"\n{inst}: no matching products"); continue
    p = prods[np.argmin(prods["size"])]
    print(f"\n{inst}: {p['productFilename']}  ({int(p['size'])/1e6:.0f} MB)")
    try:
        with fits.open(MAST_DL + p["dataURI"], use_fsspec=True, lazy_load_hdus=True) as h:
            for i, hdu in enumerate(h):
                hd = hdu.header
                shape = hd.get("NAXIS1", hd.get("ZNAXIS1")), hd.get("NAXIS2", hd.get("ZNAXIS2"))
                print(f"  [{i}] {hd.get('EXTNAME', 'PRIMARY'):10} {type(hdu).__name__:14} shape={shape} BUNIT={hd.get('BUNIT')}")
    except Exception as e:
        print(f"  FAILED: {type(e).__name__}: {str(e)[:200]}")
