import gzip
import io
import math
from urllib.parse import parse_qs, urlparse

import numpy as np
import pytest
from astropy.io import fits
from astropy.table import Table
from astropy.wcs import WCS

from fakes import DEC, RA, FakeSession, wcs_header
from fits_fetcher import footprint
from fits_fetcher.archives import ArchiveError, irsa
from fits_fetcher.archives.base import Target
from fits_fetcher.config import Settings
from fits_fetcher.output import write_credits
from fits_fetcher.processing import Options, process, save
from fits_fetcher.transfer import Transfer

M51 = Target(query="M51", matched_id="M 51", ra=RA, dec=DEC, size_arcmin=9.0)
COVERS = "POLYGON 202.37 47.10 202.57 47.10 202.57 47.30 202.37 47.30"
MISSES = "POLYGON 203.37 47.10 203.57 47.10 203.57 47.30 203.37 47.30"
WISE = "https://irsa.ipac.caltech.edu/ibe/data/wise/allwise/p3am_cdd/20/2029/2029p469_ac51/2029p469_ac51-{}-int-3.fits"
SEIP = "https://irsa.ipac.caltech.edu/data/SPITZER/Enhanced/SEIP/images/x/r1.IRAC.{}.mosaic.fits"


def sia_table(rows):
    cols = ["obs_collection", "dataproduct_subtype", "energy_bandpassname", "obs_id", "access_url", "s_region",
            "s_ra", "s_dec", "em_min", "em_max", "t_min", "t_exptime", "s_xel1", "s_xel2"]
    default = ["wise_allwise", "science", "W1", "x", WISE.format("w1"), COVERS, 202.47, 47.20, 3.0e-6, 3.8e-6,
               55400.0, 8.8, 4095, 4095]
    return Table(rows=[[r.get(c, d) for c, d in zip(cols, default)] for r in rows], names=cols)


@pytest.fixture
def fake_sia(monkeypatch):
    calls = []

    def install(rows):
        def query(self, target, radius_deg, collections):
            calls.append(collections)
            return sia_table(rows)
        monkeypatch.setattr(irsa.IrsaArchive, "_query", query)
        return calls
    return install


@pytest.mark.parametrize("name, expected", [
    ("IRAC1", ("IRAC1", "IRAC1")), ("IRAC 4.5", ("IRAC2", "IRAC2")), ("MIPS24", ("MIPS24", "MIPS1")),
    ("W3", ("W3", "W3")), ("K", ("Ks", "K")), ("Ks", ("Ks", "K")), ("J", ("J", "J")), ("IRAS 60", None),
])
def test_band_of(name, expected):
    assert irsa.band_of(name) == expected


def test_grid_keys():
    assert irsa.grid_key("wise_allwise", WISE.format("w3")) == "WISE tile 2029p469_ac51 box"
    j = "https://irsa.ipac.caltech.edu/ibe/data/twomass/allsky/allsky/980527n/s024/image/ji0240232.fits.gz"
    assert irsa.grid_key("twomass_allsky", j) == "2MASS image 980527n-0240232 box"
    assert irsa.grid_key("twomass_allsky", j.replace("/ji", "/ki")) == irsa.grid_key("twomass_allsky", j)
    seip = "https://irsa.ipac.caltech.edu/data/SPITZER/Enhanced/SEIP/images/5/0058/50058000/0/50058000-0/50058000.50058000-0.{}.mosaic.fits"
    assert irsa.grid_key("spitzer_seip", seip.format("IRAC.1")) == irsa.grid_key("spitzer_seip", seip.format("IRAC.4")) \
        == "Spitzer region 50058000-0 IRAC box"
    assert irsa.grid_key("spitzer_seip", seip.format("MIPS.1")) == ""
    short = seip.replace("-0.{}", "-0-short.{}").format("IRAC.1")
    assert irsa.grid_key("spitzer_seip", short) == "Spitzer region 50058000-0 IRAC box"  # same grid (REQ-89)
    assert irsa.short_frames(short) and not irsa.short_frames(seip.format("IRAC.1"))


def test_search_applies_selection_rules(fake_sia):
    calls = fake_sia([
        {"energy_bandpassname": "W1"},                                                  # kept
        {"energy_bandpassname": "W2", "access_url": WISE.format("w2")},                 # kept
        {"energy_bandpassname": "W1", "dataproduct_subtype": "noise"},                  # uncertainty map
        {"energy_bandpassname": "W3", "s_region": MISSES},                              # misses the centre
        {"energy_bandpassname": "IRAS60"},                                              # unknown band
        {"obs_collection": "wise_unwise", "energy_bandpassname": "W1"},                 # not an allowed collection
        {"obs_collection": "spitzer_seip", "energy_bandpassname": "IRAC1", "access_url": SEIP.format(1),
         "s_xel1": 3000, "s_xel2": 2500},
    ])
    found = irsa.IrsaArchive(Settings()).search(M51, 0.02)
    assert calls == [["spitzer_seip", "wise_allwise", "twomass_allsky"]]
    assert sorted(p.filter for p in found) == ["IRAC1", "W1", "W2"]
    w1 = next(p for p in found if p.filter == "W1")
    assert (w1.archive, w1.telescope, w1.instrument, w1.collection) == ("IRSA", "WISE", "AllWISE atlas", "wise_allwise")
    assert w1.wavelength_um == 3.4 and w1.pixel_scale_arcsec == 1.375 and w1.boxed and w1.grid == "WISE tile 2029p469_ac51 box"
    # 1.5 x 9' box at 1.375"/px, cut by IBE: 590 px square of float32
    assert (w1.width, w1.height, w1.size_bytes) == (590, 590, 590 * 590 * 4)
    assert "hips2fits" in w1.thumbnail_url and "allWISE%2FW1" in w1.thumbnail_url and w1.coverage > 0.99
    ir1 = next(p for p in found if p.filter == "IRAC1")
    assert (ir1.telescope, ir1.instrument, ir1.pixel_scale_arcsec, ir1.grid) == ("Spitzer", "IRAC", 0.6, "")
    assert ir1.size_bytes == (1350 + 128) * 3000 * 4  # whole rows of the 1350 px box, plus margins


def test_short_frame_mosaics_are_listed_and_labelled(fake_sia):
    url = "https://irsa.ipac.caltech.edu/data/SPITZER/Enhanced/SEIP/images/5/0057/50057690/0/50057690-0/50057690.50057690-0{}.IRAC.1.mosaic.fits"
    fake_sia([{"obs_collection": "spitzer_seip", "energy_bandpassname": "IRAC1", "access_url": url.format(s),
               "obs_id": f"r1{s}", "t_exptime": e} for s, e in (("", 104.0), ("-short", 3.9))])
    full, short = sorted(irsa.IrsaArchive(Settings()).search(M51, 0.02), key=lambda p: p.chip)
    assert (full.chip, short.chip) == ("", "short frames") and "short frames only" in short.product_level
    assert full.filter == short.filter == "IRAC1" and full.grid == short.grid != ""


def test_only_ticked_collections_and_no_planets(fake_sia):
    calls = fake_sia([{}])
    assert irsa.IrsaArchive(Settings(irsa_collections=["twomass_allsky", "herschel_x"])).search(M51, 0.02) == []
    assert calls == [["twomass_allsky"]]  # the W1 row is from a collection that wasn't ticked
    saturn = Target(query="saturn", matched_id="Saturn", ra=0, dec=0, body="Saturn")
    assert irsa.IrsaArchive(Settings()).search(saturn, 0.02) == [] and len(calls) == 1


def test_query_failure_becomes_archive_error(monkeypatch):
    class Down:
        def __init__(self, *a, **kw):
            pass

        def search(self, **kw):
            raise OSError("503 Server Error: Service Unavailable for url: https://irsa.ipac.caltech.edu/SIA?POS=…")
    monkeypatch.setattr(irsa.pyvo.dal, "SIA2Service", Down)
    with pytest.raises(ArchiveError, match=r"^its image search is temporarily unavailable \(HTTP 503\)"):
        irsa.IrsaArchive(Settings()).search(M51, 0.02)


def test_boxed_products_ignore_the_cutout_option(product):
    assert not Options(cutout=True).for_product(product(boxed=True)).cutout


# ---------- downloads ----------
def tile(value: float, n: int = 400, scale: float = 1.375) -> fits.Header:
    h = wcs_header(n, n, scale)
    h["CRPIX1"] += 37  # the tile's centre isn't the object
    h["CRPIX2"] -= 21
    return h


class IbeSession(FakeSession):
    """Answers IBE cutout requests like the real service: the pixels around `center`, `size` wide, on the file's own
    grid, gzipped; clipped at the image edge."""

    def get(self, url, headers=None, stream=False, timeout=None):
        base, _, query = url.partition("?")
        if query and url not in self.files:
            q = {k: v[0] for k, v in parse_qs(query).items()}
            with fits.open(io.BytesIO(self.files[base])) as h:
                data, hdr = h[0].data, h[0].header.copy()
            ra, dec = (float(v) for v in q["center"].split(","))
            x, y = WCS(hdr).all_world2pix([[ra, dec]], 0)[0]
            n = math.ceil(float(q["size"].removesuffix("arcmin")) * 60 / abs(hdr["CD2_2"] * 3600))  # 16.8' → 734 px
            x0, y0 = max(0, round(x) - n // 2), max(0, round(y) - n // 2)
            x1, y1 = min(data.shape[1], round(x) - n // 2 + n), min(data.shape[0], round(y) - n // 2 + n)
            hdr["CRPIX1"] -= x0
            hdr["CRPIX2"] -= y0
            buf = io.BytesIO()
            fits.PrimaryHDU(data[y0:y1, x0:x1], hdr).writeto(buf)
            self.files[url] = gzip.compress(buf.getvalue())
        return super().get(url, headers, stream, timeout)


def fits_bytes(data, header) -> bytes:
    buf = io.BytesIO()
    fits.PrimaryHDU(data.astype(">f4"), header).writeto(buf)
    return buf.getvalue()


def wise_products(target):
    rows = [{"energy_bandpassname": b, "access_url": WISE.format(b.lower())} for b in ("W1", "W4")]
    return [irsa.IrsaArchive(Settings())._product(r, target) for r in sia_table(rows)]


def test_wise_bands_get_the_same_box_on_their_own_grid(tmp_path):
    t = Target(query="x", matched_id="X", ra=RA, dec=DEC, size_arcmin=1.0)  # box 1.5' = 66 px at 1.375"
    rng = np.random.default_rng(2)
    files = {WISE.format(b): fits_bytes(rng.normal(100, 1, (400, 400)), tile(0)) for b in ("w1", "w4")}
    session = IbeSession(files)
    outs = []
    for p in wise_products(t):
        f = irsa.IrsaArchive(Settings()).fetch(p, t, Transfer(tmp_path, session=session), 2.0, lambda d, n: None)
        assert not f.box_clipped and "cut by IRSA's cutout service" in f.notes[0]
        r = process(f, p, t, Options(star_repair=False, cutout=True, box_arcmin=2.0).for_product(p))
        outs.append(r)
    assert [r.data.shape for r in outs] == [(66, 66), (66, 66)]
    assert all(r.header["CRPIX1"] == outs[0].header["CRPIX1"] and r.header["CRPIX2"] == outs[0].header["CRPIX2"] for r in outs)
    x, y = WCS(outs[0].header).all_world2pix([[RA, DEC]], 0)[0]
    assert abs(x - 32.5) <= 1 and abs(y - 32.5) <= 1
    hist = "".join(str(c) for c in outs[0].header["HISTORY"])
    assert "1.5 arcmin box" in hist and outs[0].header["FFCUTOUT"] is False
    assert not outs[0].warnings


def test_box_past_the_tile_edge_is_clipped_and_reported(tmp_path):
    t = Target(query="x", matched_id="X", ra=RA, dec=DEC, size_arcmin=20.0)  # 30' box: bigger than the 9' tile
    files = {WISE.format("w1"): fits_bytes(np.full((400, 400), 5.0), tile(0))}
    p = wise_products(t)[0]
    f = irsa.IrsaArchive(Settings()).fetch(p, t, Transfer(tmp_path, session=IbeSession(files)), 2.0, lambda d, n: None)
    assert f.box_clipped
    r = process(f, p, t, Options(star_repair=False).for_product(p))
    assert r.data.shape == (400, 400)
    assert any("ran past the image edge" in w for w in r.warnings)


def test_spitzer_fetches_only_the_box_rows(tmp_path):
    t = Target(query="x", matched_id="X", ra=RA, dec=DEC, size_arcmin=0.5)  # box 0.75' = 75 px at 0.6"
    h = wcs_header(300, 900, 0.6)
    data = np.random.default_rng(3).normal(10, 1, (900, 300))
    session = FakeSession({SEIP.format(1): fits_bytes(data, h)})
    p = irsa.IrsaArchive(Settings())._product(sia_table([{
        "obs_collection": "spitzer_seip", "energy_bandpassname": "IRAC1", "access_url": SEIP.format(1),
        "s_xel1": 300, "s_xel2": 900}])[0], t)
    f = irsa.IrsaArchive(Settings()).fetch(p, t, Transfer(tmp_path, session=session), 2.0, lambda d, n: None)
    data_req = [rng for u, rng in session.requests if rng and int(rng.split("=")[1].split("-")[0]) >= 2880]
    fetched = sum(int(b) - int(a) + 1 for a, b in (r.removeprefix("bytes=").split("-") for r in data_req[-1:]))
    assert fetched == (75 + 2 * irsa.ROW_MARGIN_PX) * 300 * 4  # the box's rows and margins, not 900 rows
    r = process(f, p, t, Options(star_repair=False).for_product(p))
    assert r.data.shape == (75, 75)
    x, y = WCS(r.header).all_world2pix([[RA, DEC]], 0)[0]
    assert abs(x - 37) <= 1 and abs(y - 37) <= 1
    (x0, x1, y0, y1), _ = footprint.pixel_box(h, RA, DEC, 0.75, (900, 300))
    assert np.allclose(r.data, data[y0:y1, x0:x1].astype(np.float32))


def test_credits_name_irsa(tmp_path, product):
    t = Target(query="x", matched_id="X", ra=RA, dec=DEC, size_arcmin=1.0)
    files = {WISE.format("w1"): fits_bytes(np.full((400, 400), 5.0), tile(0))}
    p = wise_products(t)[0]
    f = irsa.IrsaArchive(Settings()).fetch(p, t, Transfer(tmp_path, session=IbeSession(files)), 2.0, lambda d, n: None)
    save(process(f, p, t, Options(star_repair=False).for_product(p)), tmp_path / "X" / "set" / "W1.fits")
    text = " ".join(write_credits(tmp_path / "X").read_text().split())
    assert "AllWISE" in text and "NASA/IPAC Infrared Science Archive" in text


def test_size_estimate_allows_for_the_image_edge():
    """REQ-86: M51 sits 382 px across a 512 x 1024 px 2MASS image, so a 1008 px box keeps about 512 x 721 px."""
    t = Target(query="M51", matched_id="M 51", ra=202.469575, dec=47.19525833, size_arcmin=11.2)
    url = "https://irsa.ipac.caltech.edu/ibe/data/twomass/allsky/allsky/980527n/s024/image/ji0240232.fits.gz"
    # the image centre that puts M51 at pixel (382.2, 807.1), as measured in verification step 19
    c_dec = t.dec - (807.1 - 511.5) / 3600
    c_ra = t.ra - (382.2 - 255.5) / 3600 / np.cos(np.radians(c_dec))
    p = irsa.IrsaArchive(Settings())._product(sia_table([{
        "obs_collection": "twomass_allsky", "energy_bandpassname": "J", "access_url": url,
        "s_ra": c_ra, "s_dec": c_dec, "s_xel1": 512, "s_xel2": 1024}])[0], t)
    assert abs(p.width - 512) <= 2 and abs(p.height - 721) <= 2
