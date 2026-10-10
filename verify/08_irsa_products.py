"""Verification 08: IRSA pipeline collections (REQ-56): what one result row resolves to via DataLink,
and the HDU structure of the science file (headers only). Run: .venv/bin/python verify/08_irsa_products.py
"""
import astropy.units as u
import pyvo
from astropy.coordinates import SkyCoord
from astropy.io import fits
from astroquery.ipac.irsa import Irsa

c = SkyCoord.from_name("M51")
for coll in ["spitzer_seip", "wise_allwise", "twomass_allsky"]:
    t = Irsa.query_sia(pos=(c, 0.01 * u.deg), collection=coll)
    print(f"\n===== {coll}: {len(t)} rows =====")
    print("  bands:", sorted({str(b) for b in t["energy_bandpassname"]}))
    print("  calib levels:", sorted({str(b) for b in t["calib_level"]}), " access_format:", sorted({str(b) for b in t["access_format"]})[:3])
    for col in ("dataproduct_subtype", "obs_title", "s_resolution", "access_estsize", "s_xel1", "jpegURL"):
        if col in t.colnames:
            print(f"  {col}: {[str(v)[:70] for v in t[col][:3]]}")
    sci_rows = t[t["dataproduct_subtype"] == "science"]
    print("  subtypes:", sorted({str(v) for v in t["dataproduct_subtype"]}), "| science rows:", len(sci_rows),
          "| science access_format:", sorted({str(v) for v in sci_rows["access_format"]}))
    r = sci_rows[0]
    print("  science file URL:", str(r["access_url"])[-90:])
    url = str(r["access_url"])
    if "datalink" in str(r["access_format"]):
        links = pyvo.dal.DatalinkResults.from_result_url(url).to_table()
        print("  DataLink entries for first row:")
        for l in links:
            print(f"    {str(l['semantics']):14} {str(l['content_type'])[:28]:28} {str(l['description'])[:50]:50} {str(l['access_url'])[-60:]}")
        sci = [l for l in links if str(l["semantics"]) == "#this"]
        url = str(sci[0]["access_url"]) if sci else url
    try:
        with fits.open(url, use_fsspec=True, lazy_load_hdus=True) as h:
            for i, hdu in enumerate(h):
                hd = hdu.header
                print(f"  science file [{i}] {type(hdu).__name__} BITPIX={hd.get('BITPIX')} {hd.get('NAXIS1')}x{hd.get('NAXIS2')} "
                      f"BUNIT={hd.get('BUNIT')} BSCALE={hd.get('BSCALE')} CTYPE1={hd.get('CTYPE1')} MAGZP={hd.get('MAGZP')}")
    except Exception as e:
        print(f"  header read FAILED: {type(e).__name__}: {str(e)[:150]}")
