import pytest

from fits_fetcher.archives.base import Product
from fits_fetcher.filters import parse


def make_product(filter="F814W", instrument="ACS/WFC", archive="MAST", collection="HST", obs_id=None,
                 exptime=1000.0, date="2020-01-01", scale=0.05, size=100_000_000, **kw) -> Product:
    wl, band = parse(filter, instrument)
    return Product(archive=archive, collection=collection, telescope=collection, instrument=instrument,
                   filter=filter, obs_id=obs_id or f"{instrument}-{filter}-{exptime}-{date}", url="https://example/x.fits",
                   wavelength_um=wl, band_type=band, exptime_s=exptime, obs_date=date,
                   pixel_scale_arcsec=scale, size_bytes=size, **kw)


@pytest.fixture
def product():
    return make_product
