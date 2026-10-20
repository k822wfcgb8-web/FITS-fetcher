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
    # ESO (REQ-90). Keys are the `eso_telescopes` setting's names; each holds several ESO data collections.
    "VISTA": {
        "name": "VISTA",
        "full_name": "Visible and Infrared Survey Telescope for Astronomy (ESO)",
        "facts": [
            ("Mirror", "4.1 m"),
            ("Where", "Cerro Paranal, Chile (ground-based)"),
            ("Active", "VIRCAM camera 2009–2023"),
            ("Camera used", "VIRCAM: 16 detectors with wide gaps; six shifted 'pawprints' make one gap-free tile "
                            "of about 1.5 deg², 0.34″ pixels. FITS-fetcher uses the tiles only."),
            ("Wavelengths", "Z 0.88, Y 1.02, J 1.25, H 1.65 and Ks 2.15 µm (near-infrared)"),
            ("Surveys", "VHS (whole southern sky), VVV and VVVX (Milky Way plane and bulge), VMC (Magellanic "
                        "Clouds), VIKING, VIDEO, UltraVISTA and others"),
        ],
        "artifacts": [
            "Depth is uneven across a tile: strips along two edges are covered by one pawprint instead of two, so "
            "they're noisier.",
            "The sky is subtracted on scales of a few arcminutes, so faint light around large galaxies and "
            "nebulae can be removed or leave dark halos.",
            "Bright stars saturate, with ghost rings, cross-talk dots along detector rows and persistence.",
            "Different filters are separate tiles on slightly different pixel grids, so they need registration.",
            "Pixel values are in instrument units (ADU); the header's PHOTZP gives the magnitude scale.",
        ],
        "link": "https://www.eso.org/public/teles-instr/paranal-observatory/surveytelescopes/vista/",
        "link_label": "Telescope page at ESO",
    },
    "VST": {
        "name": "VST",
        "full_name": "VLT Survey Telescope (ESO)",
        "facts": [
            ("Mirror", "2.6 m"),
            ("Where", "Cerro Paranal, Chile (ground-based)"),
            ("Active", "Since 2011"),
            ("Camera used", "OmegaCAM: 32 CCDs covering 1° × 1°, 0.21″ pixels. FITS-fetcher uses combined images "
                            "only (KiDS, FDS, VEGAS and other deep coadds), not single-pointing pawprints."),
            ("Wavelengths", "u, g, r, i, z (0.33–0.92 µm) and an Hα narrowband filter (NB_659)"),
        ],
        "artifacts": [
            "Reflections inside the camera put large, faint halos and ghosts around bright stars.",
            "Narrow lines along the CCD gaps where fewer exposures overlap.",
            "Satellite trails, partly removed when exposures are combined.",
            "Most objects are only in g and r, or not covered at all: few of ESO's VST surveys were released as "
            "combined images.",
            "Pixel values are in instrument units (ADU or ADU/s); the header's PHOTZP gives the magnitude scale.",
        ],
        "link": "https://www.eso.org/public/teles-instr/paranal-observatory/surveytelescopes/vst/",
        "link_label": "Telescope page at ESO",
    },
    "HAWKI": {
        "name": "VLT",
        "full_name": "Very Large Telescope, Unit Telescope 4 (ESO), with HAWK-I",
        "facts": [
            ("Mirror", "8.2 m"),
            ("Where", "Cerro Paranal, Chile (ground-based)"),
            ("Active", "HAWK-I since 2007; adaptive optics (GRAAL) since 2017"),
            ("Camera used", "HAWK-I: four detectors with a 15″ cross-shaped gap, 7.5′ field, 0.106″ pixels; "
                            "stacks of several shifted exposures"),
            ("Wavelengths", "Y, J, H, Ks (0.97–2.31 µm) and narrowband filters such as Brγ, H₂ and NB2090"),
        ],
        "artifacts": [
            "A cross-shaped strip through the middle with less depth, where the four detectors' gaps were covered "
            "by fewer exposures.",
            "The four detectors' quarters can have different background levels, so one quarter may look darker "
            "(seen in an M83 Ks stack, verification step 20).",
            "The field is only 7.5′ across: larger objects are covered by several pointings, each its own image.",
            "Sky subtraction removes light spread over most of the field, so large nebulae can look patchy.",
            "Bright stars saturate, with persistence and cross-talk.",
            "Pixel values are in instrument units (ADU); the header's PHOTZP gives the magnitude scale.",
        ],
        "link": "https://www.eso.org/sci/facilities/paranal/instruments/hawki.html",
        "link_label": "Instrument page at ESO",
    },
    "SOFI": {
        "name": "NTT",
        "full_name": "New Technology Telescope (ESO), with SOFI",
        "facts": [
            ("Mirror", "3.58 m"),
            ("Where", "La Silla, Chile (ground-based)"),
            ("Active", "SOFI from 1998; the images FITS-fetcher finds are mostly from PESSTO (since 2012)"),
            ("Camera used", "SOFI: one detector, 4.9′ field, 0.29″ pixels; stacks of shifted exposures"),
            ("Wavelengths", "J 1.25, H 1.65 and Ks 2.16 µm (near-infrared)"),
        ],
        "artifacts": [
            "Mostly supernova follow-up, so exposures are short and the images shallow; the galaxy is there "
            "because a supernova went off in it.",
            "The field is only 4.9′ across, so large galaxies are cut off.",
            "Cross-talk and residual sky patterns from the short exposures.",
        ],
        "link": "https://www.eso.org/sci/facilities/lasilla/instruments/sofi.html",
        "link_label": "Instrument page at ESO",
    },
    # CADC (REQ-95). Keys are the `cadc_telescopes` setting's names; each holds one or more CADC collections.
    "CFHT": {
        "name": "CFHT",
        "full_name": "Canada-France-Hawaii Telescope",
        "facts": [
            ("Mirror", "3.6 m"),
            ("Where", "Maunakea, Hawaiʻi (ground-based)"),
            ("Active", "Since 1979; MegaCam since 2003, WIRCam since 2005"),
            ("Cameras used", "MegaCam: 40 CCDs covering 1° × 1°, as CADC's MegaPipe stacks, 0.186″ pixels. "
                             "WIRCam: four near-infrared detectors, 20′ field, as CADC's WIRWOLF stacks, 0.3″ pixels."),
            ("Wavelengths", "MegaCam u, g, r, i, z (0.33–1.0 µm) plus Hα and [OIII] narrowband; WIRCam J, H, Ks "
                            "(1.2–2.3 µm)"),
            ("Surveys", "CFHT Legacy Survey, Next Generation Virgo Survey (NGVS), and many single programmes"),
        ],
        "artifacts": [
            "Faint, large halos and reflections around bright stars, and ghost images of the telescope pupil.",
            "Narrow strips of lower depth along the gaps between MegaCam's CCDs, where fewer exposures overlap.",
            "The sky is subtracted on scales of several arcminutes, so the outer light of large galaxies and "
            "nebulae can be dimmed.",
            "Two generations of MegaPipe tiles: older ones about 1.6° across, newer ones 31′; both may be listed.",
            "Pixel values are scaled so that the header's PHOTZP (30) gives AB magnitudes.",
        ],
        "link": "https://www.cfht.hawaii.edu/",
        "link_label": "Telescope page at CFHT",
    },
    "SUBARU": {
        "name": "Subaru",
        "full_name": "Subaru Telescope (National Astronomical Observatory of Japan), with Suprime-Cam",
        "facts": [
            ("Mirror", "8.2 m"),
            ("Where", "Maunakea, Hawaiʻi (ground-based)"),
            ("Active", "Since 1999; Suprime-Cam 1999–2017"),
            ("Camera used", "Suprime-Cam: 10 CCDs covering 34′ × 27′, 0.2″ pixels, as stacks made by CADC"),
            ("Wavelengths", "B, V, Rc, Ic and g, r, i, z (0.38–1.0 µm), plus narrowband filters"),
        ],
        "artifacts": [
            "Long bleed trails and halos from bright stars, which saturate quickly on an 8 m telescope.",
            "Strips of lower depth along the CCD gaps, and uneven edges where the exposures don't overlap.",
            "Depth varies widely between filters: some stacks are a single short exposure, others many hours.",
            "No magnitude zero point in the header.",
        ],
        "link": "https://www.subarutelescope.org/",
        "link_label": "Telescope page at Subaru",
    },
}


def for_collections(collections: list[str]) -> dict[str, dict]:
    """The fact sheets of these collections, in the given order, skipping any without one."""
    return {c: TELESCOPES[c] for c in collections if c in TELESCOPES}
