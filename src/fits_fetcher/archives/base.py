"""Common interface for archive modules (S-20) and the shared data model."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from astropy.io import fits

from fits_fetcher.config import Settings

if TYPE_CHECKING:
    from fits_fetcher.transfer import Progress, Transfer


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
    centre_ra: float | None = None      # image centre as the archive reports it, degrees (REQ-59)
    centre_dec: float | None = None
    offset_arcmin: float | None = None  # how far the object lies from that centre
    grid: str = ""                      # images with the same grid stack pixel-for-pixel (REQ-60); "" = unknown
    coverage: float | None = None       # share of the object inside the delivered image, 0-1 (REQ-69)
    parts: list[str] = field(default_factory=list)  # Pan-STARRS skycells stitched into one box (REQ-68)
    region: str = ""                    # the archive's footprint (STC-S s_region), for off-centre sets (REQ-71)
    # REQ-71: an off-centre set's image is cut to the pixel box enclosing these sky points (ra, dec), the area
    # all the set's filters share; `spot` names that area and keeps the key apart from the uncut product.
    cut: list[tuple[float, float]] = field(default_factory=list)
    spot: str = ""

    @property
    def key(self) -> str:
        base = f"{self.archive}:{self.collection}:{self.obs_id}:{self.filter}"
        return f"{base}:{self.spot}" if self.spot else base

    def to_dict(self) -> dict:
        d = asdict(self)
        d["key"] = self.key
        return d


@dataclass
class Fetched:
    """A science image downloaded to the cache, ready to be read into memory by the processing step."""
    primary: fits.Header            # the file's primary header (instrument, filter, programme keywords)
    header: fits.Header             # the science HDU's header; WCS shifted if only some rows were fetched
    path: Path                      # file holding the pixels
    hdu: int | str | None = None    # None: `path` holds only the science data bytes (REQ-57); else the HDU to open
    files: list[Path] = field(default_factory=list)  # cache files to delete once the output is saved (REQ-23)
    box: tuple[int, int, int, int] | None = None     # (x0, x1, y0, y1) to cut around the object, in these pixels
    box_clipped: bool = False                         # the box ran past the image edge (REQ-58 warning)
    notes: list[str] = field(default_factory=list)   # HISTORY lines about how the image was fetched
    # REQ-68: pieces pasted into one canvas of `header`'s size: (file, HDU, x offset, y offset) of each piece's
    # pixel (0, 0) in the canvas. Each piece is linearised on its own before pasting.
    stitch: list[tuple[Path, int, int, int]] = field(default_factory=list)
    url: str = ""                                     # the address actually read, if not the product's own


@dataclass
class InsideGroup:
    """Images of one archive target, from one instrument, inside a large searched object (REQ-70)."""
    name: str           # the archive's target name, e.g. "NGC-2438"
    archive: str
    instrument: str
    filters: list[str]  # in wavelength order
    ra: float           # where the images point
    dec: float
    collection: str = ""  # e.g. "HST", for the telescope name (REQ-73)


@dataclass
class InsideObject:
    """Another object with colour sets inside the searched object, identified by the resolver (REQ-70)."""
    name: str           # e.g. "NGC 2438"
    ra: float
    dec: float
    offset_arcmin: float                 # from the searched object's centre
    sets: list[InsideGroup] = field(default_factory=list)


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

    def elsewhere(self, target: Target) -> list[Product]:
        """REQ-71: images overlapping `target`'s disc that can form off-centre sets; each carries its `region`
        and `grid`. Grouping into sets happens in spots.py."""
        return []

    def inside(self, target: Target, min_filters: int) -> list[InsideGroup]:
        """REQ-70: colour sets of other targets inside `target` (images that overlap it but miss its centre)."""
        return []

    def fetch(self, product: Product, target: Target, transfer: Transfer, box_arcmin: float,
              progress: Progress) -> Fetched:
        """Download the science image of `product` (REQ-08, REQ-57). `box_arcmin` is the cut-around size, used by
        products that are always cut (REQ-58) to fetch only the rows needed."""
        raise ArchiveError(f"Downloading from {self.name} isn't built yet.")
