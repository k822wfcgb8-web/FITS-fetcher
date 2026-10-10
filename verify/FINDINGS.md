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

## 02 — ESO, IRSA, CADC (2026-10-10, `02_eso_irsa_cadc.py` plus follow-up queries)

**ESO: TAP service works** (`https://archive.eso.org/tap_obs`, table `ivoa.ObsCore`). It has a `filter` column, `access_url`, `access_estsize` and `abmaglim`. M51 returned 0 rows, which is expected: at Dec +47° it is outside the reach of ESO's Chilean telescopes. **To re-test with a southern object** (M42, NGC 7293).

**IRSA: use SIA, not ObsCore TAP.**
- IRSA's ObsCore TAP table is incomplete: for M51 it held only WISE, NEOWISE, 2MASS, IRAS and SPHEREx — **no Spitzer or Herschel**.
- `astroquery.ipac.irsa.Irsa.query_sia` returns far more: Spitzer (`spitzer_seip`, `spitzer_sings`, `spitzer_lvl`, `spitzer_simla`, `spitzer_mips_lg`), Herschel community products (`herschel_dustpedia`, `herschel_vngs`, `herschel_hhli`), WISE (`wise_allwise`, `wise_unwise`, `wise_z0mgs`), 2MASS (`twomass_allsky`, `twomass_lga`), SOFIA, AKARI.
- **`calib_level` is unreliable as a filter here:** 2MASS atlas images, which are co-added, are labelled level 2. IRSA needs an **allow-list of collections**, not a `calib_level >= 3` rule.
- `calib_level` can be blank (masked) in results; code must handle that.
- Results return `access_url` as a **DataLink** document, not the FITS file directly, so download needs one extra step to resolve the real file URL.
- **Same duplication pattern as HST/HLA/HLSP:** Spitzer data appear as the IRSA pipeline mosaics (`spitzer_seip`) and as several community re-reductions (SINGS, LVL, SIMLA). Herschel at IRSA is **only** community products; the Herschel pipeline archive is at ESA, which is out of scope.

**CADC: not reachable from this machine during testing.** `ws-cadc.canfar.net` resolves but the connection times out; the older `www.cadc-ccda.hia-iha.nrc-gc.ca` name no longer exists. May be a temporary outage or a local network restriction. **To retry.**

## 03 — ESO southern objects; CADC retry (2026-10-10, `03_eso_south_cadc_retry.py`)

**ESO: works, but `calib_level` can't be used as a filter.** Every ESO image product for M42, NGC 7293 and M16 is labelled `calib_level = 2`, including reduced Phase 3 tiles and stacks. A `calib_level >= 3` rule would return nothing. Selection must use **collection/instrument allow-lists plus `dataproduct_subtype`**:
- `dataproduct_subtype = 'pawprint'` marks unmerged multi-chip products (VIRCAM, OmegaCAM, HAWK-I, VIMOS, SPHERE) → excluded under REQ-12.
- Blank subtype rows are the combined products: VISTA tiles (VHS, VVVX), HAWK-I stacks.
- Results also include **ALMA** (interferometry, out of scope), **APEX bolometer maps** at 870 µm (beyond far-IR, outside REQ-20) and **NGTS** (time-series survey, out of scope). The allow-list handles these.
- **Consequence of REQ-12:** for these objects all VST/OmegaCAM optical data (VST-ATLAS, VPHAS+, ad-hoc programmes) were pawprints only, so ESO contributes **mainly near-IR** (VISTA J/H/Ks/Y tiles, HAWK-I J/H/Ks/Brγ). To check whether KiDS coadds (combined VST tiles) appear for objects in the KiDS footprint.
- Useful extra columns: `filter`, `access_estsize`, `abmaglim` (depth), `multi_ob`/`n_obs`.

**CADC: still unreachable**, also from outside Claude Code's sandbox (`ws-cadc.canfar.net` port 443 times out after 20 s). So the problem is on CADC's side or between this network and CADC, not a local restriction. **To retry on another day;** if it persists, look for CADC's current service address in their documentation.

## 04 — Candidate list for ambiguous names (REQ-18) (`04_name_candidates.py`)

**Works via SIMBAD TAP**, searching SIMBAD's `NAME …` identifiers with a **starts-with** match:
- "Crab" → M 1 (SNR) and the Crab Pulsar; "Eagle" → M 16 and an unrelated supernova; "Orion" → 20 candidates (M 42, Orion A/B clouds, Orion Dwarf Galaxy…). Each query took 0.1–0.4 s.
- **Contains-anywhere matching is unusable**: `lowercase(id) LIKE '%crab%'` ran over 10 minutes. SIMBAD's ADQL has `lowercase()` but no `LOWER`, `UPPER` or `ILIKE`.
- SIMBAD's case-sensitive matching needs the term as typed **and** in Title Case. Combining the two with `OR` in one query took 105 s, so send **one query per variant** and merge the results.
- Several identifiers can point at the same object (M 1 ← "Crab", "Crab Nebula"), so **deduplicate by `main_id`**. Some candidates (Orion Arm, Orion Belt) have **no coordinates** and must be dropped.
- Catalogue designations (M51, NGC 5194) should go straight to Sesame (`from_name`), as in step 01. The candidate list is for common names.

## 05/06 — Pan-STARRS encoding (REQ-36) (`05_panstarrs_encoding.py`, `06_panstarrs_formula.py`)

**Confirmed:** full PS1 stack files (`*.stk.<band>.unconv.fits`, about 68 MB, 6307×6289) are **Rice tile-compressed 16-bit integers** in extension 1, asinh-encoded with `BOFFSET` and `BSOFTEN`. The linearisation

    flux = BOFFSET + BSOFTEN * 2 * sinh(x / (2.5 / ln 10))     (x after BSCALE/BZERO)

matches the PS1 cutout service's linear output to within 1 part in 10⁶ over 57,600 pixels.
- The PS1 **cutout service** (`fitscut.cgi`) already returns linear 32-bit float; no conversion is needed for cutouts.
- Blank pixels are NaN after decoding (70,296 of 39.7 M in the M51 r stack).
- Weight (`.wt`) and mask (`.mask`) are **separate files**, not extensions, so REQ-32 is satisfied by not downloading them.
- MAST's PS1 product list includes **`.cmf` source catalogues labelled `SCIENCE`**; select PS1 images by filename pattern (`.stk.<band>.unconv.fits`).
- PS1 headers use the **old `PC001001`-style WCS keywords** (astropy warns). Rewrite them in the modern form before saving so PixInsight/Siril read the WCS reliably (REQ-49).

## 07 — Science extension and DQ arrays in combined products (`07_hdu_structure.py`)

Read with HTTP range requests (headers only); **MAST supports partial reads**.

| Product | Science HDU | Other HDUs | DQ array? |
|---|---|---|---|
| HST ACS/WFC, WFC3/UVIS `_drc`; WFC3/IR `_drz` | `SCI` [1], e⁻/s | WHT, CTX, HDRTAB | **No** |
| JWST NIRCam / MIRI `_i2d` | `SCI` [1], MJy/sr | ERR, CON, WHT, VAR_POISSON, VAR_RNOISE, VAR_FLAT, HDRTAB, ASDF | **No** |
| PS1 stack | ext [1] (compressed) | (separate wt/mask files) | Separate mask file |

- **REQ-37's data-quality "saturated" check has nothing to read** in HST/JWST combined products: they carry no DQ array. Only the NaN/zero rule applies to them.
- The science array is a fraction of the file: an HST `_drc` is about 215 MB for a 4k×4k image (SCI is about a third), and a JWST NIRCam `_i2d` is about 301 MB (SCI is about a seventh). Because MAST allows partial reads, the app could fetch **only the `SCI` extension**.

## 08 — IRSA pipeline products (REQ-56) (`08_irsa_products.py`)

- Each SIA row is **one file**, labelled `dataproduct_subtype` = `science` / `noise` / `weight` / `auxiliary`. Select `science` only (REQ-32). Science rows give a **direct FITS URL** (no DataLink step for these collections).
- `spitzer_seip`: IRAC1–4, MIPS24 mosaics, single HDU, `BITPIX=-32`, MJy/sr. Several mosaics per band for M51 (REQ-53 applies).
- `wise_allwise`: W1–W4 atlas tiles 4095×4095, single HDU, float, **DN** with `MAGZP`.
- `twomass_allsky`: J/H/K atlas images 512×1024, float, `MAGZP`, **delivered gzipped** (`.fits.gz`) → decompress during extraction (REQ-46). Labelled `calib_level` 2 although they are co-adds (see step 02).
- Single-HDU products need no extension selection; WCS uses `RA---TAN` (Spitzer) or `RA---SIN` (WISE, 2MASS).

## 09 — Thumbnail sources (REQ-27) (`09_thumbnails.py`)

- **MAST:** archive preview JPEGs exist (`jpegURL` column, `_drc.jpg`), but can be large (1.2 MB for one ACS image).
- **IRSA:** the IBE service cuts a small FITS piece from any science file (`?center=ra,dec&size=200pix`, about 130 KB, gzipped). Render to PNG for display.
- **CDS hips2fits:** returns 200×200 JPEGs (5–10 KB) for HST, AllWISE, 2MASS and Pan-STARRS HiPS surveys. These show the **survey**, not the exact archive file, so they're suitable only as a fallback.
- **ESO:** not checked yet.
- **PS1:** the cutout service (step 05) can also make thumbnails.

## Not yet verified
- **CADC** collection list and mirrors (REQ-21/35): service unreachable (step 03).
- **KiDS** coadds at ESO for optical coverage; ESO thumbnails.
- **Licence compatibility** (REQ-34) of dependencies.

## 10 — siril-cli scripting (REQ-50) (`10_siril_cli.py`)

**Confirmed: Siril 1.4.4's `siril-cli` can be scripted.** On macOS it is at `/Applications/Siril.app/Contents/MacOS/siril-cli` (not on `PATH`). Run `siril-cli -d <dir> -s <script.ssf>`; a script of `requires 1.4.0` / `load <file>` / `stat` / `close` loads the file and prints statistics. **The exit code is 0 on success and 1 on failure**, so tests can rely on it.

| Test file | Siril result |
|---|---|
| `good.fits`: single HDU, `BITPIX -32`, no scaling (the app's output format) | Loads; statistics match the source exactly |
| `multi_hdu.fits`: empty primary + image extension | Loads (Siril takes the first image) |
| `scaled.fits`: 16-bit with `BSCALE`/`BZERO` | **Fails**: "Numerical overflow during type conversion" |
| `compressed.fits`: Rice tile-compressed | Loads, but values differ slightly (max 382,220.9 vs 382,213.7), because Rice compression of floats is **lossy** |

This supports REQ-46 (no compression) and REQ-47 (no scaling) as written. The `stat` output doesn't show whether Siril read the WCS; check that separately (e.g. with a plate-solve-free Siril command) when tests are written.
