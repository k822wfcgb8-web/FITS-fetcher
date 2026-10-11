"""Footprint tests for REQ-14 / REQ-17: does an image's sky region contain the object's centre?

Archives describe footprints as IVOA STC-S strings in `s_region`, e.g.
"POLYGON 202.1 47.0 202.8 47.0 202.8 47.4 202.1 47.4" (optionally with a frame such as ICRS),
sometimes as several polygons, or as "CIRCLE ra dec radius".
"""
from __future__ import annotations

import math
import re

_SHAPE = re.compile(r"(POLYGON|CIRCLE|BOX)\b", re.IGNORECASE)
_NUMBER = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")


def shapes(s_region: str) -> list[tuple[str, list[float]]]:
    """The shapes of an s_region: (kind, numbers), e.g. ("POLYGON", [ra1, dec1, ra2, dec2, ...])."""
    parts = _SHAPE.split(s_region or "")
    shapes = []
    for kind, body in zip(parts[1::2], parts[2::2]):
        nums = [float(n) for n in _NUMBER.findall(body)]
        shapes.append((kind.upper(), nums))
    return shapes


def angular_sep_deg(ra1: float, dec1: float, ra2: float, dec2: float) -> float:
    r1, d1, r2, d2 = map(math.radians, (ra1, dec1, ra2, dec2))
    s = math.sin((d2 - d1) / 2) ** 2 + math.cos(d1) * math.cos(d2) * math.sin((r2 - r1) / 2) ** 2
    return math.degrees(2 * math.asin(min(1.0, math.sqrt(s))))


def _gnomonic(ra: float, dec: float, ra0: float, dec0: float) -> tuple[float, float] | None:
    """Project (ra, dec) onto the tangent plane at (ra0, dec0). None if on the far hemisphere."""
    r, d, r0, d0 = map(math.radians, (ra, dec, ra0, dec0))
    cos_c = math.sin(d0) * math.sin(d) + math.cos(d0) * math.cos(d) * math.cos(r - r0)
    if cos_c <= 0:
        return None
    x = math.cos(d) * math.sin(r - r0) / cos_c
    y = (math.cos(d0) * math.sin(d) - math.sin(d0) * math.cos(d) * math.cos(r - r0)) / cos_c
    return x, y


def _point_in_polygon(px: float, py: float, poly: list[tuple[float, float]]) -> bool:
    inside = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > py) != (y2 > py):
            x_cross = x1 + (py - y1) * (x2 - x1) / (y2 - y1)
            if px < x_cross:
                inside = not inside
    return inside


def contains(s_region: str, ra: float, dec: float) -> bool:
    """True if any shape in `s_region` contains the point. Unparseable regions return False."""
    for kind, nums in shapes(s_region):
        if kind == "CIRCLE" and len(nums) >= 3:
            if angular_sep_deg(nums[0], nums[1], ra, dec) <= nums[2]:
                return True
        elif kind == "BOX" and len(nums) >= 4:
            # BOX ra dec width height, axis-aligned on the tangent plane at its centre
            p = _gnomonic(ra, dec, nums[0], nums[1])
            if p and abs(math.degrees(p[0])) <= nums[2] / 2 and abs(math.degrees(p[1])) <= nums[3] / 2:
                return True
        elif kind == "POLYGON" and len(nums) >= 6:
            verts = list(zip(nums[0::2], nums[1::2]))
            # Project around the target itself, so the test point is the origin.
            projected = [_gnomonic(vr, vd, ra, dec) for vr, vd in verts]
            if any(p is None for p in projected):
                continue  # polygon spans more than a hemisphere from the target; can't contain it sensibly
            if _point_in_polygon(0.0, 0.0, projected):
                return True
    return False


def area_deg2(s_region: str) -> float | None:
    """Approximate sky area of an s_region (sum of its shapes), for download-size estimates."""
    total = 0.0
    for kind, nums in shapes(s_region):
        if kind == "CIRCLE" and len(nums) >= 3:
            total += math.pi * nums[2] ** 2
        elif kind == "BOX" and len(nums) >= 4:
            total += nums[2] * nums[3]
        elif kind == "POLYGON" and len(nums) >= 6:
            verts = list(zip(nums[0::2], nums[1::2]))
            ra0 = verts[0][0]
            dec0 = sum(v[1] for v in verts) / len(verts)
            pts = [_gnomonic(r, d, ra0, dec0) for r, d in verts]
            if any(p is None for p in pts):
                continue
            pts = [(math.degrees(x), math.degrees(y)) for x, y in pts]
            total += abs(sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1]))) / 2
    return total or None


def box_arcmin(size_arcmin: float | None, default_arcmin: float) -> float:
    """Cut-around size (REQ-25, REQ-58): 2x the object's size, or the default when the size is unknown."""
    return 2 * size_arcmin if size_arcmin else default_arcmin


def stitch_box_arcmin(size_arcmin: float | None, default_arcmin: float) -> float:
    """Pan-STARRS box (REQ-68): 1.5x the object's size, or the default cutout box when the size is unknown."""
    return 1.5 * size_arcmin if size_arcmin else default_arcmin


def _offsets(ra0: float, dec0: float, pts: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Tangent-plane offsets (degrees) → sky positions around (ra0, dec0)."""
    r0, d0 = math.radians(ra0), math.radians(dec0)
    out = []
    for x, y in pts:
        x, y = math.radians(x), math.radians(y)
        rho = math.hypot(x, y)
        c = math.atan(rho)
        if rho == 0:
            out.append((ra0, dec0))
            continue
        dec = math.asin(math.cos(c) * math.sin(d0) + y * math.sin(c) * math.cos(d0) / rho)
        ra = r0 + math.atan2(x * math.sin(c), rho * math.cos(d0) * math.cos(c) - y * math.sin(d0) * math.sin(c))
        out.append((math.degrees(ra) % 360, math.degrees(dec)))
    return out


def disc_points(ra: float, dec: float, radius_deg: float, n: int = 21) -> list[tuple[float, float]]:
    """Evenly spaced sky positions filling a disc (an n x n grid, kept inside the circle)."""
    step = 2 * radius_deg / (n - 1)
    grid = [(-radius_deg + i * step, -radius_deg + j * step) for i in range(n) for j in range(n)]
    return _offsets(ra, dec, [(x, y) for x, y in grid if x * x + y * y <= radius_deg ** 2 + 1e-12])


def box_points(ra: float, dec: float, side_deg: float, n: int = 25) -> list[tuple[float, float]]:
    """Evenly spaced sky positions filling a square box centred on (ra, dec), edges included."""
    h, step = side_deg / 2, side_deg / (n - 1)
    return _offsets(ra, dec, [(-h + i * step, -h + j * step) for i in range(n) for j in range(n)])


def coverage(regions: list[str], ra: float, dec: float, size_arcmin: float | None) -> float | None:
    """REQ-69: share of the object's disc lying inside any of `regions` (0-1); None if the size is unknown."""
    if not size_arcmin:
        return None
    pts = disc_points(ra, dec, size_arcmin / 2 / 60)
    inside = sum(1 for p in pts if any(contains(r, *p) for r in regions))
    return inside / len(pts)


def tangent_arcsec(ras, decs, ra0: float, dec0: float):
    """Vectorised gnomonic projection around (ra0, dec0), in arcsec (x east, y north). Arrays in, arrays out."""
    import numpy as np

    r, d = np.radians(np.asarray(ras, dtype=float)), np.radians(np.asarray(decs, dtype=float))
    r0, d0 = math.radians(ra0), math.radians(dec0)
    cos_c = np.sin(d0) * np.sin(d) + np.cos(d0) * np.cos(d) * np.cos(r - r0)
    x = np.cos(d) * np.sin(r - r0) / cos_c
    y = (np.cos(d0) * np.sin(d) - np.sin(d0) * np.cos(d) * np.cos(r - r0)) / cos_c
    return np.degrees(x) * 3600, np.degrees(y) * 3600


def sky_from_tangent(xs, ys, ra0: float, dec0: float) -> list[tuple[float, float]]:
    """Inverse of tangent_arcsec for a list of points."""
    return _offsets(ra0, dec0, [(x / 3600, y / 3600) for x, y in zip(xs, ys)])


def polygons_arcsec(s_region: str, ra0: float, dec0: float) -> list:
    """The POLYGON shapes of an s_region projected around (ra0, dec0): a list of (n, 2) arrays in arcsec."""
    import numpy as np

    out = []
    for kind, nums in shapes(s_region):
        if kind == "POLYGON" and len(nums) >= 6:
            x, y = tangent_arcsec(nums[0::2], nums[1::2], ra0, dec0)
            out.append(np.column_stack([x, y]))
    return out


def inside_mask(polygons: list, xs, ys):
    """Which of the points (xs, ys) lie inside any of `polygons` (even-odd rule, so concave outlines work)."""
    import numpy as np

    xs, ys = np.asarray(xs, dtype=float), np.asarray(ys, dtype=float)
    mask = np.zeros(xs.shape, dtype=bool)
    for poly in polygons:
        (x_lo, y_lo), (x_hi, y_hi) = poly.min(axis=0), poly.max(axis=0)
        near = (xs >= x_lo) & (xs <= x_hi) & (ys >= y_lo) & (ys <= y_hi)
        if not near.any():
            continue
        px, py = xs[near], ys[near]
        hit = np.zeros(px.shape, dtype=bool)
        for (x1, y1), (x2, y2) in zip(poly, np.roll(poly, -1, axis=0)):
            if y1 == y2:
                continue
            crosses = (y1 > py) != (y2 > py)
            hit ^= crosses & (px < x1 + (py - y1) * (x2 - x1) / (y2 - y1))
        mask[near] |= hit
    return mask


def position_angle_deg(ra0: float, dec0: float, ra: float, dec: float) -> float:
    """Direction from (ra0, dec0) to (ra, dec), degrees east of north."""
    r0, d0, r, d = map(math.radians, (ra0, dec0, ra, dec))
    pa = math.atan2(math.sin(r - r0), math.cos(d0) * math.tan(d) - math.sin(d0) * math.cos(r - r0))
    return math.degrees(pa) % 360


def compass(pa_deg: float) -> str:
    """8-point compass name for a position angle: 0 → N, 90 → E."""
    return ("N", "NE", "E", "SE", "S", "SW", "W", "NW")[int((pa_deg + 22.5) // 45) % 8]


def points_box(header, points: list[tuple[float, float]], shape: tuple[int, int]
               ) -> tuple[tuple[int, int, int, int], bool]:
    """Pixel box enclosing sky `points`: ((x0, x1, y0, y1), clipped), zero-based, end-exclusive (REQ-71).

    Images on one pixel grid get the same box from the same points, so they stay pixel-aligned (REQ-60).
    """
    import warnings

    import numpy as np
    from astropy.wcs import WCS, FITSFixedWarning

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", FITSFixedWarning)
        w = WCS(header).celestial
    px = w.all_world2pix(np.asarray(points, dtype=float), 0)
    x0, y0 = (math.floor(v + 0.5) for v in px.min(axis=0))
    x1, y1 = (math.floor(v + 0.5) + 1 for v in px.max(axis=0))
    ny, nx = shape
    box = (max(0, x0), min(nx, x1), max(0, y0), min(ny, y1))
    if box[0] >= box[1] or box[2] >= box[3]:
        raise ValueError("The shared area lies outside this image.")
    return box, box != (x0, x1, y0, y1)


def pixel_box(header, ra: float, dec: float, size_arcmin: float, shape: tuple[int, int] | None
              ) -> tuple[tuple[int, int, int, int], bool]:
    """Square pixel box centred on (ra, dec): ((x0, x1, y0, y1), clipped), zero-based, end-exclusive.

    Integer arithmetic only after one rounding, so images on one pixel grid get exactly the same box
    and stay pixel-aligned (REQ-58, REQ-60). `clipped` is True when the box ran past the image edge.
    With `shape` None the box isn't clipped (REQ-68: it may span several Pan-STARRS skycells).
    """
    import warnings

    from astropy.wcs import WCS, FITSFixedWarning
    from astropy.wcs.utils import proj_plane_pixel_scales

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", FITSFixedWarning)
        w = WCS(header).celestial
    x, y = w.all_world2pix([[ra, dec]], 0)[0]
    scale_arcsec = float(proj_plane_pixel_scales(w).mean()) * 3600
    n = max(1, math.ceil(round(size_arcmin * 60 / scale_arcsec, 6)))  # round: 21.0000001 px is 21
    x0, y0 = math.floor(x + 0.5) - n // 2, math.floor(y + 0.5) - n // 2
    if shape is None:
        return (x0, x0 + n, y0, y0 + n), False
    ny, nx = shape
    box = (max(0, x0), min(nx, x0 + n), max(0, y0), min(ny, y0 + n))
    clipped = box != (x0, x0 + n, y0, y0 + n)
    if box[0] >= box[1] or box[2] >= box[3]:
        raise ValueError("The object lies outside this image.")
    return box, clipped
