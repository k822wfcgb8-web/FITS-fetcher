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

## 11 — Found while building the MAST module (2026-10-10)

- **HST product families (→ REQ-58).** For M51 F814W the `HST` collection holds 1 multi-visit mosaic (`hst_skycell-…_all`), 37 HAP single-visit images (`hst_<prop>_<visit>_…`) and 34 classic-pipeline copies (`jd8f…`) of the same exposures. All multi-visit mosaics of one skycell share **one pixel grid** (21,258 × 20,668 px at 0.04″ for M51's skycell, identical `CRVAL`/`CRPIX` for ACS/WFC, WFC3/UVIS and WFC3/IR `_all`).
- **WFC3/IR mosaics come twice:** `_all` on the shared 0.04″ grid and `_coarse-all` at 0.12″. Only `_all` aligns with the other filters.
- **`_total_` HAP products** are white-light sums of several filters; excluded.
- **Filter names:** HAP joins parts with `-` (`F606W-POL0V`), the classic pipeline with `;`. Polarizer (`POL…`) and ramp (`FR…`) images are not colour channels; excluded.
- **Speed:** `Observations.get_product_list` took 56 of 60 s for M51 (26,862 file entries for 168 observations), because each HAP observation lists every exposure inside it. File addresses follow fixed patterns, checked with HTTP HEAD on 2026-10-10:
  - HST ACS/WFC and WFC3/UVIS: `mast:HST/product/<obs_id>_drc.fits`
  - other HST (ACS/HRC, WFC3/IR, WFPC2): `mast:HST/product/<obs_id>_drz.fits`
  - JWST: `mast:JWST/product/<obs_id>_i2d.fits`
  - PS1: `https://ps1images.stsci.edu/rings.v3.skycell/<proj>/<sub>/<obs_id>.unconv.fits`

  Building them directly cut the search to under a second. `tests/test_network.py` re-checks one file of each kind.
- **JWST NIRCam `_i2d` files** can be large mosaics (2.4 GB for one F164N product), which makes REQ-57's science-only download important.

## 12 — Images that share one pixel grid (REQ-60) (`12_shared_grids.py`)

Science-extension headers only, read over HTTP on 2026-10-10.

- **HST single-visit (HAP) images from the same visit share one grid**, whatever the filter. M1, WFC3/UVIS, proposal 17500: F502N, F631N and F673N of visit 06 have identical `NAXIS`, `CRVAL`, `CRPIX` and `CD` (6116 × 6089 px); visit 04 has its own shared grid (6115 × 6087 px, different `CRVAL`); F487N of visit 08 matches neither. Same visit = stack pixel-for-pixel; different visits = needs registration.
  **WFPC2/PC behaves the same** (checked while building): proposal 8222 visit 04 F502N, F631N and F673N share 4429 × 4404 px with identical `CRVAL`/`CRPIX`; proposal 5206 visit 02 F502N does not.
- **Pan-STARRS stacks in the same skycell share one grid** across all five bands (M1 skycell 1784.059: 6279 × 6261 px, identical `CRVAL`/`CRPIX`/`CDELT`/`PC`). A neighbouring skycell (M51 2261.085 vs 2261.075) has the same projection centre but a different `CRPIX2`, so it does not line up.
- **HST multi-visit mosaics** of one skycell share one grid (step 11).
- **JWST `_i2d`** products are resampled per filter, often at different pixel scales (0.031″ / 0.063″ for NIRCam); not treated as shared.

## 13 — Download and processing chain on real MAST files (`13_download_chain.py`)

Full chain (fetch → linearise → star-core repair → cutout → NaN to 0 → header → check → save) on M51, 2026-10-10. Five products, 16–18 s in total.

| Product | Fetched | Output | Repair | Siril |
|---|---|---|---|---|
| HST WFC3/IR F110W single-visit | `SCI` only (range read) | 1185 × 1071 px | 0 regions | loads |
| JWST MIRI F770W `_i2d` | `SCI` only (range read) | 1112 × 1033 px | 3 regions, 14 px | loads |
| PS1 r stack | whole file (68 MB, Rice-compressed) | 6307 × 6289 px | 12 regions, 1,898 px | loads |
| HST ACS/WFC mosaics, 2 filters | box rows only (+64-row margin) | 1500 × 1500 px each (1′ box) | 0 regions | loads |

- **Range reads:** MAST (`Download/file`) and `ps1images.stsci.edu` both answer `Range` requests with 206.
- **Mosaic cutouts:** the object is at the box centre (750.1, 750.2), and both filters have identical `NAXIS`, `CRVAL`, `CRPIX` and `PC`/`CDELT`. They stack pixel-for-pixel, as REQ-58 requires.
- **PS1 WCS:** the old `PC001001` keywords are rewritten as `PC1_1`/`CDELT`. Positions agree with the original header to 10⁻⁸″ across the image.
- **PS1 linearity:** `BOFFSET`/`BSOFTEN` are gone from the output. The median sky is 8.3 and the brightest pixels are about 10⁶, so the values are linear, not asinh-compressed.
- **Clean-up:** no cache files were left once the outputs were saved (REQ-23).
- **siril-cli:** `-d` changes the working folder before the `-s` script is read, so the script path must be absolute.
- **Not yet tested on real files:** a full-size HST mosaic (about 1.8 GB for M51's 18′ box), to check memory use during repair.

## 14 — Large masked holes around bright stars (REQ-67), M37 Pan-STARRS

The Pan-STARRS i and z stacks of M37 had black areas that star-core repair left alone. They are stack masks around very bright stars (rectangles and streaks of 2,056–18,123 px), over the 2,000 px limit of REQ-38.

To tell star holes apart from blank areas, I measured the brightest tenth of the pixels within 3 px of each large hole, in σ above a sigma-clipped sky:

| Hole | Size | Edge brightness | Kind |
|---|---|---|---|
| i, bright star | 18,123 px | 102σ | star |
| i, star near the cluster core | 5,282 px | 505σ | star |
| z, bright star | 6,117 px | 523σ | star |
| i, streaks running away from the bright star | 3,571 px (12 px wide) | 6σ | not touching the star |
| i and y, blocks in empty sky | 2,056 and 2,941 px | 6σ and 2σ | blank |
| image borders (PS1, HST, JWST) | — | 1.5–6σ | blank |

- **Rule:** a 25σ threshold with a 50,000 px limit fills exactly the three star holes.
- **What stays black:** the streaks, by the "stars only" choice, and the empty-sky blocks.
- **No side effects:** the rule fills nothing in the M51 test files (step 13).
- **Fill quality:** the rim-inward fill gives natural-looking saturated cores. Where a mask runs out into the sky, the fill is a grey, faceted smear rather than black.
- **Option tested and not adopted:** filling from another filter on the same grid (r → i) gave more realistic stars. But a linear fit to the rim, which is dominated by the star, left flat bright bars over the sky.

## 15 — Whole-object Pan-STARRS boxes, coverage and objects inside (REQ-68–70), M46

**Why M46 showed only one set.** At M46's centre, MAST holds only the Pan-STARRS skycell 0994.022, plus TESS images, which are excluded. Within the 25′ cluster, the HST images are of NGC 2438 (6.6′ from the centre) and OH 231.8+04.2 (10.5′). They miss the cluster's centre, so REQ-14 leaves them out. The skycell that was shown covered only **51%** of the cluster; the four skycells overlapping M46 together cover 100%.

**Skycells share one pixel lattice.** Skycells 0994.022, 023, 032 and 033 have the same CRVAL, CDELT and PC, CRPIX offsets of whole pixels (5,762 × 5,774), and overlap by about 480 px. They can be stitched with no resampling.

**PS1 cutout service** (`fitscut.cgi`, checked 2026-10-10):
- returns linear 32-bit floats on the skycell's grid, with CRPIX shifted by whole pixels;
- `size=w,h` gives a rectangle; the cutout starts at `x − w//2`, `y − h//2`;
- 196 MB took 12 s.

Cutouts are uncompressed, so per skycell the app fetches either the cutout or the whole compressed file (68 MB), whichever is smaller.

**Results:**

| Object | Box | Skycells | Downloaded | Time |
|---|---|---|---|---|
| M46, r | 37.9′ (9108 px) | 6 | 262 MB | 17 s |
| M51, r | 13.6′ (3256 px) | 4 | 56 MB | 6 s |

Before, M51 came as one 68 MB skycell with the galaxy near a corner. Now each object is at the centre of its box, the image loads in siril-cli, and the 12 × 12 background blocks show no steps at skycell joins. The dip around M46's core is Pan-STARRS's own sky subtraction around the bright cluster.

**MAST timing varies a lot today.** The same query took 3–35 s, and M42 at a 0.25° radius returned 5,222 rows in 35 s. So the PS1 query runs in parallel with the main query, and the objects-inside query (capped at 0.25°) runs after the results are shown.

**Objects inside.** Archive target names were looked up in one SIMBAD `ident IN (…)` query (0.4 s).
- M51: 18 archive names became 4 objects (SN 2005cs, M51 OT2019-1, SN 2011dh, NGC 5195). Its own pointings (`M51-POS4`, `NGC5194-1`) and labels (`ANY`) were dropped.
- M46: `QXPUP` joined OH 231.8+04.2.
- Searching NGC 2438 from the list found its WFPC2 narrowband set (68% coverage) and a Pan-STARRS box (100%).

## 16 — Why M35 showed one set, and off-centre sets (REQ-71), 2026-10-11

**Where the M35 images went.** M35 (NGC 2168, 38′ across) at MAST, step by step, within its 19′ radius:

| Stage | Images |
|---|---|
| Combined, public, allowed instruments (HST, JWST, PS1) | 2,880 |
| HST duplicates removed (classic pipeline and mosaics; REQ-58) | 506 |
| Footprint contains the cluster's centre (REQ-14) | 9 |
| At least 3 filters from one instrument (REQ-10, REQ-11) | 5 (Pan-STARRS g r i z y) |

The duplicate step only drops copies of the same exposures. The centre rule removes 497 of 506: HST fields are 2–3′ wide, and nearly all M35 pointings are WFC3/ACS calibration fields (programmes 13101, 14020, 13571; 1–40 s exposures) or WFPC2 parallels. REQ-70 hid the rest: it drops the searched object's own pointings (`M-35`) and unknown labels (`ANY`, `PAR`).

**Why the MAST Portal shows more.** A portal search on M35 (3′) returns 11,802 rows: 10,104 light curves (TESS/K2), 8,487 raw files, and HLA/HLSP reprocessings (the groups overlap). Only 38 images of any kind contain the centre.

**Off-centre groups.** Without the centre rule, 23 combinations of 3–5 filters from one instrument cover a common spot inside M35, in about 7 places. Most combine different pointings (WFPC2), so they'd need registration. On one pixel grid (REQ-71), after duplicates and slivers are dropped, 6 sets remain (search 0.1 s after the 0.7–30 s disc query):

| Set | Position | Shared area | Source |
|---|---|---|---|
| ACS/WFC F502N, F555W, F606W, F658N | 4.3′ NW | 2.9 arcmin² | skycell p1869x11y04 mosaics, 2–137 s |
| WFC3/UVIS F555W, F606W, F814W | 5.9′ SW | 7.4 arcmin² | visit 13101_b1, 5–10 s |
| WFC3/UVIS F410M, F502N, F606W | 1.9′ E | 6.0 arcmin² | skycell p1869x11y04 mosaics, 16–57 s |
| WFC3/UVIS F410M, F502N, F606W | 3.2′ E | 1.8 arcmin² | skycell p1869x10y04 mosaics |
| ACS/WFC F502N, F550M, F606W | 6.9′ SE | 1.7 arcmin² | skycell p1869x10y04 mosaics |
| ACS/WFC F502N, F550M, F606W | 8.0′ E | 0.7 arcmin² | skycell p1869x10y04 mosaics |

- The 5-filter WFC3/UVIS mosaic group (F555W–F814W) in skycell p1785x03y20 shares only **0.19 arcmin²**, a triangle where the skycell edge clips the mosaics. It falls under the 0.25 arcmin² minimum.
- Mosaic footprints are traced outlines (often concave, up to 50 vertices), and the same sky appears in several overlapping skycells (p1785x03y20, p1786x19y20, p1869x11y04).

**Download check.**
- ACS set (4 mosaics): every filter 4490 × 1635 px with the same CRPIX/CRVAL, 0–6% blank; 600 MB fetched (full mosaic rows).
- WFC3/UVIS set (3 single-visit images): every filter 2975 × 2782 px, same grid. **49% blank**: the field is a 45° diamond in a north-up image, the same in each filter (kept, Q-57).
- Both load in siril-cli (`load`, `stat`, exit 0).

**Bug found and fixed.** `hst_13101_b1_wfc3_uvis_*_ic40b1` has only `_drz.fits`, no `_drc.fits`. The `_drc` address built for WFC3/UVIS and ACS/WFC answered HTTP 404. The MAST module now falls back to `_drz` on a 404, and the saved file's HISTORY records the address actually read. This also affected normal results.

## 17 — Mostly blank images and trimming (REQ-75, REQ-76), NGC 3675 WFPC2, 2026-10-11

**Problem.** The F336W and F450W single-visit images of visit 11128_09 (WFPC2) opened as flat grey in PixInsight after Auto Stretch (STF), with no galaxy visible. The MAST thumbnails show plenty of detail.

**Cause.** The L-shaped WFPC2 field sits on a 4512 × 4495 px canvas at 0.0455″/px; **56%** of the pixels are blank (saved as 0, REQ-22). STF works from the median and MAD of all pixels, so both are 0, the midtones balance goes to 0, and every pixel above 0 turns white (the sky noise reads as grey). Computed from the data area alone, the same stretch shows arms, dust lanes and the nucleus. The signal is also faint (counts/s; 99% of F450W below 0.022, peak 71).

**Trimming.** The box around the real data is x 4–4499, y 788–4479 (82% of the canvas); blank pixels drop to **46–47%**, under half, so STF's MAD is no longer 0 (F450W 1.2e-6) and the galaxy shows. The L-shape keeps the rest blank, so REQ-76 warns above 30%. The archive footprint (`s_region`) lands within 3 px of the data box (footprint x 6–4497, y 789–4476).

**Grid partners don't share an exact WCS.** F336W and F450W share CRPIX and CRVAL, but their PC matrices differ (PC1_1 −1.26428e-5 vs −1.26456e-5, about 0.4 px across the field). A footprint box worked out in each file came out 3722 vs 3721 rows, which would shift one filter by a pixel. So the first image on a grid records its box relative to the reference pixel (`FFGRID`, `FFTRIMBX`), and partners reuse it, from the same download or from saved files in the object's folder.

**Result** (`17_blank_borders.py`, the filters downloaded in separate jobs): both outputs 4512 × 3721 px with identical NAXIS, CRPIX and CRVAL; 47% blank with the warning on the row and in HISTORY; compatibility check ok; both load in siril-cli (exit 0).
