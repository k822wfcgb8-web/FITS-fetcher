"""Common interface for archive modules (S-20) and the shared data model."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass

from fits_fetcher.config import Settings


@dataclass(frozen=True)
class Target:
    """A resolved object (S-10): what the user typed, what the resolver matched, and where it is."""
    query: str
    matched_id: str
    ra: float
    dec: float
    object_type: str = ""
    size_arcmin: float | None = None


@dataclass
class Product:
    """One downloadable combined science image in one filter (REQ-15).

    Several products can share a filter (REQ-53); they still count as one wavelength (S-16).
    """
    archive: str            # "MAST", "ESO", "IRSA", "CADC"
    collection: str         # e.g. "HST", "PS1", "spitzer_seip"
    telescope: str
    instrument: str
    filter: str
    obs_id: str
    url: str
    wavelength_um: float | None = None
    bandwidth_um: float | None = None
    band_type: str = "broad"            # "broad" or "narrow" (REQ-19)
    exptime_s: float | None = None
    obs_date: str = ""                  # ISO date
    pixel_scale_arcsec: float | None = None
    size_bytes: int | None = None       # estimated download size (S-21, S-26)
    width: int | None = None
    height: int | None = None
    product_level: str = ""             # e.g. "HST drc", "JWST i2d", "PS1 stack"
    thumbnail_url: str = ""
    science_extension: str | int = 0    # which HDU holds the science image (S-23)
    is_mosaic: bool = False             # HST multi-visit mosaic, delivered cut around the object (REQ-58)

    @property
    def key(self) -> str:
        return f"{self.archive}:{self.collection}:{self.obs_id}:{self.filter}"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["key"] = self.key
        return d


class ArchiveError(Exception):
    """An archive was unreachable or returned something unusable (S-03, S-33)."""


class Archive(ABC):
    """One archive module. Implementations must be safe to call from a worker thread."""

    name: str = ""

    def __init__(self, settings: Settings):
        self.settings = settings

    @abstractmethod
    def search(self, target: Target, radius_deg: float) -> list[Product]:
        """Return combined, public, linear science images whose footprint contains the target's centre (REQ-14)."""
