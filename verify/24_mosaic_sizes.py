"""Verification 24: how big is an HST multi-visit mosaic file, and can the search predict it (S-26, REQ-58)?

The download estimate assumed every mosaic spans a whole skycell (21,258 px wide, from M51), but NGC 976's
mosaics turned out to be 6,100 x 5,401 px. This reads the science-extension size of mosaics around several
objects (headers only, over HTTP) and compares it with the bounding box of
  - the mosaic's own footprint (s_region), and
  - the union of every mosaic footprint on the same skycell that MAST returns,
both on the skycell's north-up 0.04" grid.
Run: .venv/bin/python verify/24_mosaic_sizes.py
"""
import warnings
from collections import defaultdict

import astropy.units as u
import numpy as np
from astropy.coordinates import SkyCoord
from astropy.io import fits
from astroquery.mast import Observations

from fits_fetcher import footprint
from fits_fetcher.archives.mast import file_url, hst_family

warnings.simplefilter("ignore")
SCALE = 0.04
OBJECTS = {"NGC 976": (38.5001586, 20.97674767), "M51": (202.469575, 47.195258), "NGC 3675": (171.5340, 43.5858),
           "M1": (83.6331, 22.0145), "M82": (148.9685, 69.6797), "NGC 4565": (189.0866, 25.9877)}


def bbox_px(regions, ra0, dec0):
    polys = [p for r in regions for p in footprint.polygons_arcsec(r, ra0, dec0)]
    xy = np.vstack(polys)
    return (np.ptp(xy[:, 0]) / SCALE, np.ptp(xy[:, 1]) / SCALE)


for name, (ra, dec) in OBJECTS.items():
    rows = Observations.query_criteria(coordinates=SkyCoord(ra * u.deg, dec * u.deg), radius=0.02 * u.deg,
                                       obs_collection="HST", dataproduct_type="image", calib_level=[3])
    mosaics = [r for r in rows if hst_family(str(r["obs_id"])) == "mosaic" and "_total_" not in str(r["obs_id"])
               and not str(r["obs_id"]).endswith("_coarse-all")]
    by_cell = defaultdict(list)
    for r in mosaics:
        by_cell[str(r["obs_id"]).split("_")[1]].append(r)
    print(f"== {name}: {len(mosaics)} mosaics on {len(by_cell)} skycell(s)")
    for cell, rs in by_cell.items():
        union = bbox_px([str(r["s_region"]) for r in rs], ra, dec)
        for r in rs[:3]:
            obs_id = str(r["obs_id"])
            with fits.open(file_url("HST", str(r["instrument_name"]), obs_id), use_fsspec=True,
                           lazy_load_hdus=True) as h:
                nx, ny = h["SCI"].header["NAXIS1"], h["SCI"].header["NAXIS2"]
            own = bbox_px([str(r["s_region"])], ra, dec)
            print(f"  {obs_id}: file {nx} x {ny} px | own footprint {own[0]:.0f} x {own[1]:.0f} "
                  f"({own[0] / nx:.2f}, {own[1] / ny:.2f}) | skycell union {union[0]:.0f} x {union[1]:.0f} "
                  f"({union[0] / nx:.2f}, {union[1] / ny:.2f})")
