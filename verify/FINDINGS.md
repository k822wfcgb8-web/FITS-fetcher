# Verification Findings

Results of checking the spec's *(verify)* items against the live archives. Library versions used: astropy 8.0.1, astroquery 0.4.11, pyvo 1.9.1 (Python 3.14).

## 01 — Name resolution and MAST (2026-10-10, `01_resolve_and_mast.py`)

**Name resolution (S-09, REQ-04/05/13): confirmed.**
- `SkyCoord.from_name` resolves Messier, NGC, IC and common names ("Whirlpool Galaxy", "Orion Nebula", "Horsehead Nebula").
- Unknown names raise `NameResolveError`, which the app can catch and turn into the "enter RA/Dec instead" message (REQ-13).
- Coordinates for some objects are coarse (IC 434 → 85.25000, −2.50000). Fine for a search centre, but worth showing to the user (S-10).
- **Open:** `from_name` returns one position only. Listing several candidates (REQ-18) needs a different call (e.g. Sesame's all-matches output or a SIMBAD query). To check in a later script.

**MAST access (Section 7.1): confirmed** via `astroquery.mast.Observations.query_criteria` with `dataproduct_type="image"`, `calib_level=[3, 4]`, `intentType="science"`, `dataRights="PUBLIC"`.
- M51 within 0.05°: 1,597 observations across HST, HLA, HLSP, JWST, PS1, SDSS, TESS and others.
- Each observation has an `s_region` footprint polygon, usable for the "contains centre" rule (REQ-14). Some footprints are huge (degrees across; e.g. survey or TESS sectors), so the rule must be applied to every result.
- Product lists mix levels: one HST observation returned calib 3 combined `_drz`/`_mos` files **and** calib 1–2 `_raw`, `_cal`, per-visit `_drz` files and JPEG previews. The app must filter at the **product** level (calib_level 3+, `productType == SCIENCE`, an allowed `productSubGroupDescription` such as DRZ/DRC/I2D/MOS), not just the observation level (REQ-15, S-15).

**New issues found:**
1. **Duplicates inside MAST.** The same HST data appear under several collections: `HST` (pipeline), `HLA` (Hubble Legacy Archive reprocessing) and `HLSP` (community high-level products). REQ-21 only handles CADC duplicates. Needs a decision.
2. **Multi-filter "detection" images.** HLA lists filter values such as `DETECTION` and `F814W;F555W;F435W`. These are combined white-light images, not single-filter science, and must be excluded (S-15 / S-16).
3. **Single files holding several bands.** SDSS shows `u;g;r;i;z` for one observation (separate frame files per band inside it). Grouping by filter has to work per product, not per observation.
4. **Non-imaging-survey results.** TESS full-frame data and STIS `MIRVIS` acquisition images appear as calib 3 "images". They should be excluded by an allow-list of collections/instruments rather than relying on the archive's flags.
