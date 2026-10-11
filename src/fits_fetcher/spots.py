"""Off-centre colour sets inside a large object (REQ-71).

Images that miss the object's centre can still form a colour set when several filters on one pixel grid
(REQ-60) cover a common area inside the object. For each grid (per instrument, unless instruments may mix):
- every filter's footprint is sampled on a fine raster of the sky (about 200 x 200 points);
- the largest filter combinations that overlap somewhere (at least `min_filters` filters) are found, and each
  connected area all of a combination's filters cover becomes one candidate set;
- a candidate must overlap the object's disc, must not contain its centre (that's a normal result), and must be
  at least MIN_AREA_ARCMIN2 (slivers where skycell edges clip a mosaic are useless).
The same sky usually appears more than once: in each visit's single-visit images and again in every skycell
mosaic that holds them (M35, verification step 16). A set is dropped when another set from the same instrument
covers most of its area with the same filters or more, and is deeper (or as deep and larger).

Each image in a set is delivered cut to the pixel box enclosing the shared area (`Product.cut`, a convex hull
of sky points), so all filters get exactly the same box on their common grid and stay pixel-aligned.
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, replace

import numpy as np
from scipy import ndimage

from fits_fetcher import footprint
from fits_fetcher.archives.base import Product, Target
from fits_fetcher.grouping import ColourSet, FilterRow, GridGroup, set_name

RASTER = 200                 # sample points across the larger side of a grid's footprints
MIN_AREA_ARCMIN2 = 0.25      # about 30" x 30"
SAME_AREA = 0.8              # share of a set's area another set must cover to replace it
MOSAIC_MARGIN_PX = 64        # extra rows fetched above and below a mosaic box (archives/mast.py)
HULL_POINTS = 64             # the shared area's outline is kept to at most this many points


@dataclass
class Spot:
    instruments: tuple[str, ...]
    filters: frozenset[str]
    products: list[Product]
    hull: list[tuple[float, float]]   # sky points whose pixel box is the delivered area
    sky: np.ndarray                   # (n, 2) ra/dec of the area's sample points (a subsample), for overlap tests
    area_arcmin2: float
    coverage: float                   # share of the object's disc inside the area
    ra: float
    dec: float
    depth: float                      # sum over filters of the deepest exposure

    def overlap(self, other: Spot) -> float:
        """Share of this area inside the other's outline."""
        poly = [footprint.polygons_arcsec(other.region, self.ra, self.dec)[0]]
        x, y = footprint.tangent_arcsec(self.sky[:, 0], self.sky[:, 1], self.ra, self.dec)
        return float(footprint.inside_mask(poly, x, y).mean())

    @property
    def region(self) -> str:
        return "POLYGON " + " ".join(f"{ra:.7f} {dec:.7f}" for ra, dec in self.hull)


def _hull(points: np.ndarray) -> np.ndarray:
    """Convex hull (monotone chain) of (n, 2) points, counter-clockwise."""
    pts = sorted(set(map(tuple, points.tolist())))
    if len(pts) <= 2:
        return np.asarray(pts)

    def half(seq):
        out = []
        for p in seq:
            while len(out) >= 2 and ((out[-1][0] - out[-2][0]) * (p[1] - out[-2][1])
                                     - (out[-1][1] - out[-2][1]) * (p[0] - out[-2][0])) <= 0:
                out.pop()
            out.append(p)
        return out[:-1]
    return np.asarray(half(pts) + half(reversed(pts)))


def _spots_on_grid(products: list[Product], target: Target, min_filters: int) -> list[Spot]:
    ra0 = float(np.mean([p.centre_ra for p in products]))
    dec0 = float(np.mean([p.centre_dec for p in products]))
    polys = {p.key: footprint.polygons_arcsec(p.region, ra0, dec0) for p in products}
    every = [poly for ps in polys.values() for poly in ps]
    if not every:
        return []
    lo = np.min([p.min(axis=0) for p in every], axis=0)
    hi = np.max([p.max(axis=0) for p in every], axis=0)
    step = max(float((hi - lo).max()) / RASTER, 0.2)
    xs = lo[0] + step * (np.arange(int((hi[0] - lo[0]) / step) + 1) + 0.5)
    ys = lo[1] + step * (np.arange(int((hi[1] - lo[1]) / step) + 1) + 0.5)
    gx, gy = np.meshgrid(xs, ys)

    by_filter: dict[str, list[Product]] = defaultdict(list)
    for p in products:
        by_filter[p.filter].append(p)
    names = sorted(by_filter)
    masks = {f: np.zeros(gx.shape, dtype=bool) for f in names}
    for f in names:
        for p in by_filter[f]:
            masks[f] |= footprint.inside_mask(polys[p.key], gx, gy)

    tx, ty = footprint.tangent_arcsec([target.ra], [target.dec], ra0, dec0)
    radius = target.size_arcmin / 2 * 60
    in_disc = (gx - tx[0]) ** 2 + (gy - ty[0]) ** 2 <= radius ** 2
    centre = (int(round((ty[0] - lo[1]) / step - 0.5)), int(round((tx[0] - lo[0]) / step - 0.5)))

    # Filter combinations present somewhere in the disc, as bit patterns; keep the largest ones.
    code = np.zeros(gx.shape, dtype=np.int64)
    for i, f in enumerate(names):
        code |= masks[f].astype(np.int64) << i
    present = {int(c) for c in np.unique(code[in_disc]) if bin(int(c)).count("1") >= min_filters}
    combos = [c for c in present if not any(o != c and o & c == c for o in present)]

    spots = []
    cell = step * step / 3600  # arcmin² per sample point
    for c in combos:
        chosen = [f for i, f in enumerate(names) if c >> i & 1]
        shared = np.logical_and.reduce([masks[f] for f in chosen])
        labels, n = ndimage.label(shared)
        for k in range(1, n + 1):
            area = labels == k
            if area.sum() * cell < MIN_AREA_ARCMIN2 or not (area & in_disc).any():
                continue
            if 0 <= centre[0] < area.shape[0] and 0 <= centre[1] < area.shape[1] and area[centre]:
                continue  # contains the object's centre: a normal result (REQ-14)
            ax, ay = gx[area], gy[area]
            # Outline from the sample cells' corners, so the box covers the cells at the area's edge.
            h = step / 2
            corners = np.concatenate([np.column_stack([ax + dx, ay + dy]) for dx in (-h, h) for dy in (-h, h)])
            hull = _hull(corners)
            if len(hull) > HULL_POINTS:
                hull = hull[np.linspace(0, len(hull) - 1, HULL_POINTS).round().astype(int)]
            members = [p for f in chosen for p in by_filter[f]
                       if footprint.inside_mask(polys[p.key], ax, ay).any()]
            sub = np.linspace(0, len(ax) - 1, min(len(ax), 400)).round().astype(int)
            sky = np.asarray(footprint.sky_from_tangent(ax[sub], ay[sub], ra0, dec0))
            (sra, sdec), = footprint.sky_from_tangent([ax.mean()], [ay.mean()], ra0, dec0)
            best = defaultdict(float)
            for p in members:
                best[p.filter] = max(best[p.filter], p.exptime_s or 0)
            spots.append(Spot(
                instruments=tuple(sorted({p.instrument for p in members})), filters=frozenset(chosen),
                products=members, hull=footprint.sky_from_tangent(hull[:, 0], hull[:, 1], ra0, dec0), sky=sky,
                area_arcmin2=float(area.sum() * cell),
                coverage=float((area & in_disc).sum() * cell / (math.pi * (target.size_arcmin / 2) ** 2)),
                ra=sra, dec=sdec, depth=sum(best.values())))
    return spots


def _better(b: Spot, a: Spot) -> bool:
    """Does `b` make `a` redundant? Same instruments, at least a's filters, most of a's area, and deeper."""
    if b is a or b.instruments != a.instruments or not a.filters <= b.filters:
        return False
    if a.overlap(b) < SAME_AREA:
        return False
    if b.filters != a.filters:
        return True
    return (b.depth, b.area_arcmin2) > (a.depth, a.area_arcmin2)


def _delivered(p: Product, spot: Spot, spot_id: str, n_filters: int) -> Product:
    """The product as delivered in this set: cut to the shared area, with its size estimate (S-26)."""
    size = p.size_bytes
    if p.is_mosaic and p.width and p.pixel_scale_arcsec:  # only the rows of the area, each a full mosaic row
        ys = [dec for _, dec in spot.hull]
        rows = math.ceil((max(ys) - min(ys)) * 3600 / p.pixel_scale_arcsec) + 2 * MOSAIC_MARGIN_PX
        size = rows * p.width * 4
    kind = "HST mosaic" if p.is_mosaic else p.product_level
    return replace(p, cut=spot.hull, spot=spot_id, coverage=spot.coverage, size_bytes=size,
                   product_level=f"{kind}, cut to the {spot.area_arcmin2:.1f} arcmin² all {n_filters} filters share")


def build(products: list[Product], target: Target, *, min_filters: int = 3,
          mix_instruments: bool = False) -> list[ColourSet]:
    """REQ-71: off-centre colour sets, most filters first, then largest share of the object."""
    if not target.size_arcmin:
        return []
    grids: dict[tuple, list[Product]] = defaultdict(list)
    for p in products:
        if p.grid and p.region and p.centre_ra is not None and p.centre_dec is not None:
            grids[(p.grid,) if mix_instruments else (p.grid, p.instrument)].append(p)

    spots = []
    for members in grids.values():
        if len({p.filter for p in members}) >= min_filters:
            spots += _spots_on_grid(members, target, min_filters)
    spots = [a for a in spots if not any(_better(b, a) for b in spots)]
    spots.sort(key=lambda s: (-len(s.filters), -s.coverage, -s.depth))

    sets = []
    for s in spots:
        offset = footprint.angular_sep_deg(target.ra, target.dec, s.ra, s.dec) * 60
        direction = footprint.compass(footprint.position_angle_deg(target.ra, target.dec, s.ra, s.dec))
        spot_id = f"{s.ra:.4f}{s.dec:+.4f}"
        by_filter: dict[str, FilterRow] = {}
        for p in s.products:
            d = _delivered(p, s, spot_id, len(s.filters))
            by_filter.setdefault(d.filter, FilterRow(d.filter, d.wavelength_um, d.band_type)).products.append(d)
        rows = sorted(by_filter.values(), key=lambda r: (r.wavelength_um is None, r.wavelength_um or 0, r.filter))
        for r in rows:  # deepest first within a filter, then newest
            r.products.sort(key=lambda p: p.obs_date, reverse=True)
            r.products.sort(key=lambda p: p.exptime_s or 0, reverse=True)
        everything = [p for r in rows for p in r.products]
        cs = ColourSet(f"{set_name(list(s.instruments), rows)}_{offset:.1f}arcmin-{direction}", list(s.instruments),
                       rows, grids=[GridGroup("A", everything[0].grid, everything)])
        cs.position = {"offset_arcmin": offset, "direction": direction, "area_arcmin2": s.area_arcmin2,
                       "ra": s.ra, "dec": s.dec}
        sets.append(cs)
    return sets
