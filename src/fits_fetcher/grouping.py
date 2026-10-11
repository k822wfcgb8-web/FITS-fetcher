"""Group products into colour sets (S-05, REQ-52) and apply the multi-wavelength rules.

- A colour set is all qualifying filters from one instrument (REQ-52); with mixing on (REQ-11),
  all instruments and archives form one set.
- Several products in one filter are listed together and count once (REQ-53, S-16).
- A set is shown only with at least `min_filters` distinct filters (REQ-07, REQ-10).
- Images on one pixel grid in two or more filters are marked as a matched group (REQ-60).
- Each set carries a colour hint (REQ-82): every filter's colour name, and suggested blue, green and red channels.
- Planets and moons (REQ-80): only images of one visit form a set, because the body moves, rotates and changes;
  the set's name ends in the visit, and sets with the same filter count are listed newest first.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from fits_fetcher import filters
from fits_fetcher.archives.base import Product


@dataclass
class FilterRow:
    filter: str
    wavelength_um: float | None
    band_type: str
    products: list[Product] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"filter": self.filter, "wavelength_um": self.wavelength_um, "band_type": self.band_type,
                "line": filters.line_for(self.wavelength_um) if self.band_type == "narrow" else None,
                "products": [p.to_dict() for p in self.products]}


@dataclass
class GridGroup:
    """Images in different filters that share one pixel grid and stack without registration (REQ-60)."""
    label: str                # "A", "B", …
    grid: str                 # e.g. "HST visit 17500_06 WFC3/UVIS"
    products: list[Product]

    def to_dict(self) -> dict:
        return {"label": self.label, "grid": self.grid, "filters": [p.filter for p in self.products],
                "product_keys": [p.key for p in self.products]}


@dataclass
class ColourSet:
    name: str
    instruments: list[str]
    rows: list[FilterRow]
    warnings: list[str] = field(default_factory=list)
    grids: list[GridGroup] = field(default_factory=list)
    # REQ-71 off-centre sets: offset_arcmin, direction, area_arcmin2, ra, dec of the shared area; None otherwise.
    position: dict | None = None
    # REQ-80 planet and moon sets: the visit, e.g. "jw01247-o301", and the date of its first image.
    visit: str = ""
    date: str = ""

    @property
    def readiness(self) -> str:
        """S-17 summary, e.g. '3 broadband filters (F435W, F555W, F814W)'."""
        broad = [r.filter for r in self.rows if r.band_type == "broad"]
        narrow = [r.filter for r in self.rows if r.band_type == "narrow"]
        bits = []
        if broad:
            bits.append(f"{len(broad)} broadband ({', '.join(broad)})")
        if narrow:
            labels = [f"{r.filter} {filters.line_for(r.wavelength_um)}" if filters.line_for(r.wavelength_um) else r.filter
                      for r in self.rows if r.band_type == "narrow"]
            bits.append(f"{len(narrow)} narrowband ({', '.join(labels)})")
        return " + ".join(bits)

    @property
    def colours(self) -> dict:
        return colour_hint(self.rows)

    @property
    def coverage(self) -> float | None:
        """REQ-69: the lowest coverage over filters, taking the best image in each; None if unknown."""
        best = [max((p.coverage for p in r.products if p.coverage is not None), default=None) for r in self.rows]
        return None if any(b is None for b in best) else min(best)

    def to_dict(self) -> dict:
        return {"name": self.name, "instruments": self.instruments, "readiness": self.readiness,
                "coverage": self.coverage,
                "warnings": self.warnings, "rows": [r.to_dict() for r in self.rows],
                "grids": [g.to_dict() for g in self.grids], "position": self.position,
                "visit": self.visit, "date": self.date, "colours": self.colours}


def colour_hint(rows: list[FilterRow]) -> dict:
    """REQ-82: each filter's colour name and swatch, and suggested channels.

    Natural colour first: if visible filters cover blue, green and red, only those are used, by colour, and the
    rest are listed as unused. Otherwise every filter with a known wavelength is split into equal thirds by count,
    moving a cut that would fall between filters within 5% in wavelength (F322W2, F323N) to the nearest wider step.
    Splitting at the largest jumps instead gave lopsided channels on M51 (NIRCam: 1, 9 and 6 filters). With two
    groups, green is left to the user (e.g. the average of blue and red).
    """
    filters_ = [{"filter": r.filter, "colour": filters.colour(r.wavelength_um)[0],
                 "swatch": filters.colour(r.wavelength_um)[1]} for r in rows]
    known = sorted((r for r in rows if r.wavelength_um), key=lambda r: r.wavelength_um)
    natural = {ch: [r.filter for r in known if lo <= r.wavelength_um < hi]
               for ch, (lo, hi) in filters.NATURAL_CHANNELS.items()}
    if all(natural.values()):
        used = {f for fs in natural.values() for f in fs}
        return {"filters": filters_, "rgb": natural, "kind": "natural colour",
                "unused": [r.filter for r in known if r.filter not in used]}
    if len(known) < 2:
        return {"filters": filters_, "rgb": None, "kind": "", "unused": []}
    groups = _thirds(known)
    if len(groups) < 2:
        return {"filters": filters_, "rgb": None, "kind": "", "unused": []}
    if len(groups) == 2:
        groups = [groups[0], [], groups[1]]
    rgb = {ch: [r.filter for r in g] for ch, g in zip("BGR", groups)}
    missing = [{"B": "blue", "G": "green", "R": "red"}[ch] for ch, fs in natural.items() if not fs]
    return {"filters": filters_, "rgb": rgb, "kind": _kind([r.wavelength_um for r in known], missing), "unused": []}


CLOSE_RATIO = 1.05  # filters closer than this in wavelength always share a channel (REQ-82)


def _thirds(rows: list[FilterRow]) -> list[list[FilterRow]]:
    """Up to three groups of near-equal size, in wavelength order, never splitting close filters."""
    n = len(rows)
    if n == 2:
        return [rows[:1], rows[1:]] if rows[1].wavelength_um / rows[0].wavelength_um >= CLOSE_RATIO else [rows]
    step = {i: rows[i].wavelength_um / rows[i - 1].wavelength_um for i in range(1, n)}
    cuts: list[int] = []
    for target in (round(n / 3), round(2 * n / 3)):
        allowed = [i for i in step if step[i] >= CLOSE_RATIO and i > (cuts[-1] if cuts else 0)]
        if allowed:
            cuts.append(min(allowed, key=lambda i: (abs(i - target), -step[i])))
    bounds = [0, *cuts, n]
    return [rows[a:b] for a, b in zip(bounds, bounds[1:])]


def _kind(wavelengths: list[float], missing: list[str]) -> str:
    lo, hi = filters.VISIBLE_UM
    uv, ir = any(w < lo for w in wavelengths), any(w >= hi for w in wavelengths)
    outside = " and ".join(x for x, on in (("UV", uv), ("infrared", ir)) if on)
    if not any(lo <= w < hi for w in wavelengths):
        return f"false colour (all {outside})" if outside != "UV and infrared" else "false colour (UV and infrared)"
    if outside:
        return f"partly natural (includes {outside})"
    return f"approximate colour (no {' or '.join(missing)} filter)"


def _grid_groups(rows: list[FilterRow]) -> list[GridGroup]:
    """Grids used in at least two filters; most filters first, then deepest."""
    by_grid: dict[str, list[Product]] = defaultdict(list)
    for r in rows:  # rows are in wavelength order, so each group's filters are too
        for p in r.products:
            if p.grid:
                by_grid[p.grid].append(p)
    matched = [ps for ps in by_grid.values() if len({p.filter for p in ps}) >= 2]
    matched.sort(key=lambda ps: (-len({p.filter for p in ps}), -sum(p.exptime_s or 0 for p in ps)))
    return [GridGroup(_label(i), ps[0].grid, ps) for i, ps in enumerate(matched)]


def _label(i: int) -> str:
    """A … Z, then AA, AB …"""
    return chr(65 + i) if i < 26 else _label(i // 26 - 1) + chr(65 + i % 26)


def set_name(instruments: list[str], rows: list[FilterRow]) -> str:
    """Folder-style name, e.g. 'ACS-WFC_F435W-F555W-F814W' (S-29)."""
    inst = "+".join(i.replace("/", "-") for i in instruments)
    return f"{inst}_{'-'.join(r.filter for r in rows)}"


def passes(product: Product, band_type: str, lines: set[str]) -> bool:
    """REQ-19 filter type and emission-line restrictions."""
    if band_type in ("broad", "narrow") and product.band_type != band_type:
        return False
    if lines:
        return product.band_type == "narrow" and filters.line_for(product.wavelength_um) in lines
    return True


def build_sets(products: list[Product], *, min_filters: int = 3, mix_instruments: bool = False,
               band_type: str = "either", lines: set[str] | None = None,
               pixel_scale_warn_ratio: float = 4.0) -> list[ColourSet]:
    lines = lines or set()
    keep = [p for p in products if passes(p, band_type, lines)]

    groups: dict[str, list[Product]] = defaultdict(list)
    for p in keep:
        groups[("all" if mix_instruments else f"{p.archive}|{p.instrument}") + f"|{p.visit}"].append(p)

    sets = []
    for members in groups.values():
        by_filter: dict[str, FilterRow] = {}
        for p in members:
            row = by_filter.setdefault(p.filter, FilterRow(p.filter, p.wavelength_um, p.band_type))
            row.products.append(p)
        if len(by_filter) < min_filters:
            continue
        rows = sorted(by_filter.values(), key=lambda r: (r.wavelength_um is None, r.wavelength_um or 0, r.filter))
        for r in rows:  # deepest first within a filter, then newest (REQ-53 leaves the choice to the user)
            r.products.sort(key=lambda p: p.obs_date, reverse=True)
            r.products.sort(key=lambda p: p.exptime_s or 0, reverse=True)
        instruments = sorted({f"{p.instrument}" for p in members})
        visit = members[0].visit
        name = set_name(instruments, rows) + (f"_{visit}" if visit else "")
        date = min((p.obs_date for p in members if p.obs_date), default="") if visit else ""
        cs = ColourSet(name, instruments, rows, grids=_grid_groups(rows), visit=visit, date=date)
        if mix_instruments:
            scales = [p.pixel_scale_arcsec for p in members if p.pixel_scale_arcsec]
            if scales and max(scales) / min(scales) > pixel_scale_warn_ratio:  # REQ-26: warn, don't block
                cs.warnings.append(f"Pixel scales differ by {max(scales) / min(scales):.0f}× "
                                   f"({min(scales):g}″ to {max(scales):g}″).")
        sets.append(cs)
    sets.sort(key=lambda s: s.date, reverse=True)  # newest first among equals (only planet sets have a date)
    sets.sort(key=lambda s: -len(s.rows))
    return sets
