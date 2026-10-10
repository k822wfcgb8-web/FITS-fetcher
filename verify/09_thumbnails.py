"""Verification 09: thumbnail sources (REQ-27). Small requests only.
Run: .venv/bin/python verify/09_thumbnails.py
"""
import io

import requests
from astropy.coordinates import SkyCoord
from astropy.io import fits

c = SkyCoord.from_name("M51")

def show(label, r):
    ctype = r.headers.get("content-type", "")
    info = ""
    if r.ok and ("fits" in ctype or r.content[:6] == b"SIMPLE"):
        h = fits.open(io.BytesIO(r.content))[0]
        info = f" FITS {h.data.shape}"
    print(f"  {label:44} HTTP {r.status_code}  {ctype[:24]:24} {len(r.content):8} bytes{info}")

print("MAST archive previews (jpegURL column):")
url = "https://mast.stsci.edu/api/v0.1/Download/file?uri=mast:HST/product/jd8f17020_drc.jpg"
show("HST drc preview JPEG", requests.get(url, timeout=60))

print("IRSA IBE cutout of a science file (small FITS to render as a thumbnail):")
base = "https://irsa.ipac.caltech.edu/ibe/data/wise/allwise/p3am_cdd/20/2029/2029p469_ac51/2029p469_ac51-w3-int-3.fits"
show("WISE W3 cutout 200 px", requests.get(base, params={"center": f"{c.ra.deg},{c.dec.deg}", "size": "200pix"}, timeout=60))
base = "https://irsa.ipac.caltech.edu/ibe/data/twomass/allsky/allsky/980527n/s024/image/hi0240232.fits.gz"
show("2MASS H cutout 200 px (gz source)", requests.get(base, params={"center": f"{c.ra.deg},{c.dec.deg}", "size": "200pix"}, timeout=60))

print("CDS hips2fits (survey-level image, not the exact archive file):")
for hips in ["CDS/P/HST/R", "CDS/P/allWISE/W1", "CDS/P/2MASS/H", "CDS/P/PanSTARRS/DR1/r"]:
    r = requests.get("https://alasky.cds.unistra.fr/hips-image-services/hips2fits",
                     params={"hips": hips, "width": 200, "height": 200, "fov": 0.2, "ra": c.ra.deg, "dec": c.dec.deg,
                             "projection": "TAN", "format": "jpg"}, timeout=60)
    show(f"hips2fits {hips}", r)
