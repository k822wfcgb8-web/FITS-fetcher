"""Planets and major moons (REQ-78). They move across the sky, so they are searched by MAST target name,
not by position, and SIMBAD (which lists no Solar System bodies) isn't asked about them.

MAST names its moving targets freely ('SATURN', 'SATURN-MAPS', 'SATURN-CENTRE', 'JUPITER+GANYMEDE'), so a body
matches every moving target whose name starts with the body's name (verification step 18).
"""
from __future__ import annotations

from fits_fetcher.archives.base import Target

PLANETS = ("Mercury", "Venus", "Mars", "Jupiter", "Saturn", "Uranus", "Neptune")
MOONS = {
    "Earth": ("Moon",),
    "Jupiter": ("Io", "Europa", "Ganymede", "Callisto"),
    "Saturn": ("Mimas", "Enceladus", "Tethys", "Dione", "Rhea", "Titan", "Iapetus"),
    "Uranus": ("Miranda", "Ariel", "Umbriel", "Titania", "Oberon"),
    "Neptune": ("Triton",),
    "Pluto": ("Charon",),
}

BODIES: dict[str, str] = {p: "Planet" for p in PLANETS}
BODIES["Pluto"] = "Dwarf planet"
BODIES.update({m: f"Moon of {parent}" for parent, moons in MOONS.items() for m in moons})


def body(text: str) -> Target | None:
    """The Solar System body called `text` (any case), or None. It has no fixed position: ra and dec are 0."""
    name = next((b for b in BODIES if b.lower() == " ".join(text.split()).lower()), None)
    if name is None:
        return None
    return Target(query=text, matched_id=name, ra=0.0, dec=0.0, object_type=BODIES[name], body=name)
