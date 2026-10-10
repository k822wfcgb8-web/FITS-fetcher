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


def _shapes(s_region: str) -> list[tuple[str, list[float]]]:
    parts = _SHAPE.split(s_region or "")
    shapes = []
    for kind, body in zip(parts[1::2], parts[2::2]):
        nums = [float(n) for n in _NUMBER.findall(body)]
        shapes.append((kind.upper(), nums))
    return shapes


def _angular_sep_deg(ra1: float, dec1: float, ra2: float, dec2: float) -> float:
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
    for kind, nums in _shapes(s_region):
        if kind == "CIRCLE" and len(nums) >= 3:
            if _angular_sep_deg(nums[0], nums[1], ra, dec) <= nums[2]:
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
    for kind, nums in _shapes(s_region):
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
