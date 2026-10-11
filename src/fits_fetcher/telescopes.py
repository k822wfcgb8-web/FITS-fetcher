"""Telescope fact sheets (REQ-74), keyed by archive collection, for the search page's telescope pop-ups.

`name` is what the page shows next to the instrument (REQ-73) and on the MAST tick boxes (REQ-72). Pixel scales
are those of the combined products FITS-fetcher downloads (archives/mast.py PIXEL_SCALE).
"""
from __future__ import annotations

TELESCOPES: dict[str, dict] = {
    "HST": {
        "name": "Hubble",
        "full_name": "Hubble Space Telescope",
        "facts": [
            ("Mirror", "2.4 m"),
            ("Where", "Low Earth orbit, about 500 km up"),
            ("Active", "Since 1990"),
            ("Cameras used", "ACS/WFC 0.05″, ACS/HRC 0.025″ (2002–2007), WFC3/UVIS 0.04″, WFC3/IR 0.128″, "
                             "WFPC2 0.1″ (1993–2009), NICMOS 0.043–0.2″ (1997–2008)"),
            ("Wavelengths", "About 0.2–2.5 µm (ultraviolet to near-infrared)"),
            ("Field of view", "Small: 2–3.4′ across, so large objects are often only partly covered"),
        ],
        "artifacts": [
            "A strip across the image from the gap between the two CCD chips (ACS/WFC, WFC3/UVIS), noisier or "
            "blank where the exposures weren't shifted to cover it.",
            "Cosmic-ray hits left where only one or two exposures overlap, often near the edges.",
            "Four-point diffraction spikes and saturated cores with bleed trails on bright stars.",
            "WFPC2 images are L-shaped, with a blank corner.",
        ],
        "link": "https://archive.stsci.edu/missions-and-data/hst",
    },
    "JWST": {
        "name": "JWST",
        "full_name": "James Webb Space Telescope",
        "facts": [
            ("Mirror", "6.5 m, made of 18 hexagonal segments"),
            ("Where", "Near the Sun–Earth L2 point, about 1.5 million km from Earth"),
            ("Active", "Launched December 2021; science since July 2022"),
            ("Cameras used", "NIRCam 0.031″ (0.6–2.3 µm) and 0.063″ (2.4–5 µm), NIRISS 0.066″, MIRI 0.11″"),
            ("Wavelengths", "About 0.6–28 µm (red to mid-infrared)"),
        ],
        "artifacts": [
            "Six-pointed diffraction spikes, plus two fainter horizontal ones, on bright stars.",
            "NIRCam: narrow gaps between its detectors and a gap of about 44″ between its two halves, "
            "unless the observation was shifted to fill them.",
            "NIRCam: faint horizontal or vertical striping from detector noise, round 'snowball' cosmic-ray hits, "
            "and faint diffuse 'wisps' in some short-wavelength images.",
            "MIRI: a cross-shaped glow around bright stars at its shortest wavelengths, and an uneven background.",
        ],
        "link": "https://archive.stsci.edu/missions-and-data/jwst",
    },
    "PS1": {
        "name": "Pan-STARRS1",
        "full_name": "Pan-STARRS1 (Panoramic Survey Telescope and Rapid Response System)",
        "facts": [
            ("Mirror", "1.8 m"),
            ("Where", "Haleakalā, Maui, Hawaiʻi (ground-based)"),
            ("Active", "3π sky survey 2010–2014, covering the sky north of declination −30°"),
            ("Camera", "GPC1: 1.4 gigapixels on 60 detector chips, a 3° field of view"),
            ("Pixel scale", "0.25″ in the stacked images; stars are about 1–1.3″ across"),
            ("Wavelengths", "About 0.4–1.1 µm, filters g, r, i, z and y"),
        ],
        "artifacts": [
            "Tilted rectangles and bands with a different background or noise: the outlines of chip gaps and "
            "masked areas in the single exposures, which lie at an angle to the stack's grid.",
            "Dark halos around large galaxies, where the background subtraction removed some of their outer light.",
            "Blank holes where every exposure was masked, often at bright stars and galaxy cores. Star-core repair "
            "fills them, but a fill across a large hole can look striped.",
            "Satellite trails, and ghost reflections near very bright stars.",
        ],
        "link": "https://archive.stsci.edu/missions-and-data/pan-starrs",
    },
}


def for_collections(collections: list[str]) -> dict[str, dict]:
    """The fact sheets of these collections, in the given order, skipping any without one."""
    return {c: TELESCOPES[c] for c in collections if c in TELESCOPES}
