"""Telescope fact sheets (REQ-74), keyed by archive collection, for the search page's telescope pop-ups.

`name` is what the page shows next to the instrument (REQ-73) and on the MAST tick boxes (REQ-72). Pixel scales
are those of the combined products FITS-fetcher downloads (archives/mast.py PIXEL_SCALE, archives/irsa.py).
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
    # IRSA (REQ-87). Collection names are IRSA's SIA collections (REQ-56).
    "spitzer_seip": {
        "name": "Spitzer",
        "full_name": "Spitzer Space Telescope",
        "facts": [
            ("Mirror", "0.85 m, cooled with liquid helium until 2009"),
            ("Where", "An Earth-trailing orbit around the Sun"),
            ("Active", "2003–2020; after the coolant ran out in 2009 only IRAC's 3.6 and 4.5 µm bands worked"),
            ("Cameras used", "IRAC (3.6, 4.5, 5.8, 8.0 µm) and MIPS 24 µm, as the Enhanced Imaging Products "
                             "mosaics: IRAC 0.6″, MIPS 2.45″ pixels"),
            ("Wavelengths", "3.6–24 µm (near- to mid-infrared)"),
        ],
        "artifacts": [
            "Bright stars leave trails along rows and columns in IRAC (\"muxbleed\" and column pulldown).",
            "Coverage is uneven: mosaic edges and gaps between pointings are noisier or blank.",
            "IRAC 5.8 and 8.0 µm are less sensitive and show more stray light; many objects observed after 2009 "
            "have only 3.6 and 4.5 µm.",
            "MIPS 24 µm: much softer images (about 6″ resolution), rings around bright sources and dark latent "
            "streaks.",
        ],
        "link": "https://irsa.ipac.caltech.edu/Missions/spitzer.html",
        "link_label": "Mission page at IRSA",
    },
    "wise_allwise": {
        "name": "WISE",
        "full_name": "Wide-field Infrared Survey Explorer (AllWISE)",
        "facts": [
            ("Mirror", "0.4 m"),
            ("Where", "Polar orbit around the Earth, about 525 km up"),
            ("Active", "AllWISE combines the 2010–2011 survey; the whole sky in four bands"),
            ("Camera", "Four detectors seeing the same field at once; atlas tiles 1.56° across"),
            ("Pixel scale", "1.375″ in the atlas images; resolution 6″ (W1–W3) and 12″ (W4)"),
            ("Wavelengths", "W1 3.4, W2 4.6, W3 12 and W4 22 µm (near- to mid-infrared)"),
        ],
        "artifacts": [
            "Atlas images are smoothed by the telescope's own blur, so stars look soft; W4 is about twice as "
            "soft as the other bands.",
            "Halos, ghost images and diffraction spikes around bright stars.",
            "W3 and W4 show bright, patchy background from interstellar dust and the zodiacal light.",
            "Pixel values are in instrument units (DN); the header's MAGZP gives the magnitude scale.",
        ],
        "link": "https://irsa.ipac.caltech.edu/Missions/wise.html",
        "link_label": "Mission page at IRSA",
    },
    "twomass_allsky": {
        "name": "2MASS",
        "full_name": "Two Micron All Sky Survey",
        "facts": [
            ("Mirror", "Two 1.3 m telescopes"),
            ("Where", "Mount Hopkins, Arizona, and Cerro Tololo, Chile (ground-based)"),
            ("Active", "1997–2001; the whole sky"),
            ("Camera", "Three detectors seeing J, H and Ks at once; atlas images 8.5′ × 17′"),
            ("Pixel scale", "1″ in the atlas images (resampled from 2″ detector pixels); stars about 2.5–3″ across"),
            ("Wavelengths", "J 1.25, H 1.65 and Ks 2.17 µm (near-infrared)"),
        ],
        "artifacts": [
            "Each image covers only 8.5′ × 17′, so large objects are cut off at its edge.",
            "Diffraction spikes, glints and persistence trails near bright stars.",
            "Background changes from airglow, especially in H, and seams between survey scans.",
            "Pixel values are in instrument units (DN); the header's MAGZP gives the magnitude scale.",
        ],
        "link": "https://irsa.ipac.caltech.edu/Missions/2mass.html",
        "link_label": "Mission page at IRSA",
    },
}


def for_collections(collections: list[str]) -> dict[str, dict]:
    """The fact sheets of these collections, in the given order, skipping any without one."""
    return {c: TELESCOPES[c] for c in collections if c in TELESCOPES}
