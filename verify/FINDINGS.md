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

**CADC retry 2026-10-12: still unreachable.** Every NRC-hosted address times out on ports 443 and 80, both inside and outside the sandbox: `ws-cadc.canfar.net` (132.246.217.37), `ws.cadc-ccda.hia-iha.nrc-cnrc.gc.ca`, `www.cadc-ccda.hia-iha.nrc-cnrc.gc.ca` and `cadcwww.dao.nrc.ca`. `www.canfar.net` (206.12.x) answers. `ws-uv.canfar.net` returns 503. CADC's and CANFAR's status pages (statuspage.io) both say "All Systems Operational", and no address change has been announced. That points to a routing or blocking problem between this network (ISP Fidium, AS13977) and NRC's 132.246.0.0/16 range, not a CADC outage. Next things to try: another network (phone hotspot) or a VPN, or ask support@canfar.net.

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

## 18 — Planets and moons (REQ-78 to REQ-81), Saturn, 2026-10-11

**Problem.** Searching 'saturn' offered only NGC 7009. SIMBAD lists no Solar System bodies, and its nearest name match is 'NAME Saturn Nebula'. Even with Saturn's position, a position search can't work: the planet moves, so each image points somewhere else.

**The article's data.** Sky at Night's JWST Saturn (processed by J. DePasquale, STScI) is programme 1247, target `SATURN-CENTRE`, NIRCam, 24–25 June 2023. It has two public visits, `jw01247-o301` and `jw01247-o341`, each with F150W2, F212N, F322W2 and F322W2+F323N (shown as F323N). A newer JWST Saturn programme (7847, target `Saturn`) is still exclusive access.

**Finding planets in MAST.** Target names vary: `SATURN`, `SATURN-MAPS`, `SATURN-2`, `SATURN07`, `SATURN-CENTRE`, `SATURN+63N-FEATURE`, `JUPITER+GANYMEDE`. A query for target name `SATURN*` with the moving-target flag (`mtFlag`), level 3, public, Hubble + JWST, answers in 0.7–3 s:

| Body | Images (allowed instruments) | Visits with 3+ filters |
|---|---|---|
| Saturn | 1,466 | 130 (2 JWST, 2 NICMOS combined, 126 Hubble single-exposure) |
| Jupiter | 3,364 | 327 (5 JWST) |
| Neptune | 2,843 | 177 (0 JWST) |

The Moon, Venus and Mercury return no moving-target images.

**Hubble products.** Hubble Advanced Products (`hst_…`) aren't made for moving targets, so every planet image is a classic product. Almost all are **single exposures** drizzled on their own (`iemr40b7q_drz.fits`; obs IDs ending in a letter), not associations (ending in a digit): for Saturn, 1,450 of 1,458 Hubble images, median 30 s. NICMOS combined products end in `_mos.fits`, so the archive's own `dataURL` is used for classic files instead of a built address.

**Result** (`18_planets.py`). 'saturn' → Saturn (Planet), NGC 7009 (PN). The search finds 1,466 images in 3.3 s and builds 130 sets of 3+ filters, one per visit. Both JWST 1247 visits appear with 4 filters. Downloaded all four filters of `jw01247-o301` (4338 × 4315 px short-wave, 2072 × 2063 px long-wave) and F395N, F502N and F631N of Hubble visit `iemr40` (2022-09-22, 2058 × 2176 px). All seven were left uncut although cutout was on, pass the compatibility check and load in siril-cli.

**What the images show.**
- **Hubble:** Saturn and its rings are clean in all three filters. F631N has 26 pixels below −100 (cosmic rays in a single exposure).
- **JWST F323N:** the dark planet with bright rings from the article.
- **JWST F150W2 and F322W2:** the disc is **saturated** in the archive's own files, so it's blank, with strong diffraction spikes and scattered light. F150W2 also shows the short-wave chip gaps.
- **Star-core repair:** it touched only small holes (160–482 regions, 201–3185 px) and left the planet's disc alone (far above the limits).

## 19 — IRSA module (REQ-85 to REQ-89), 2026-10-12 (`19_irsa_search.py`, `19b_irsa_download.py`)

**IRSA was half down all morning.** From about 08:10 EDT the SIA search, TAP and IBE search endpoints answered `503 Service Unavailable` ("maintenance downtime or capacity problems"); one SIA request at 08:17 got through. The front page, IBE file downloads, IBE cutouts and the old 2MASS SIA (`cgi-bin/2MASS/IM/nph-im_sia`) kept working. No outage was announced. The app now says "IRSA couldn't be searched: its image search is temporarily unavailable (HTTP 503). Try again later." and shows MAST's results as usual (M51: 163 images).

**WISE (AllWISE atlas), M51, tile `2029p469_ac51`.** Files are 4095 × 4095 px float, 67 MB per band, `RA---SIN`, 1.375″, DN with `MAGZP`, served with `Accept-Ranges`. IBE's cutout option (`?center=ra,dec&size=16.8arcmin`) returns a gzipped single-HDU FITS (1.4–1.9 MB, 3–13 s) of 734 px for 16.8′. **W1 and W4 cutouts have identical NAXIS, CRVAL and CRPIX**, and CRPIX differs from the tile's by whole pixels (2465, 2331), so the bands stack pixel-for-pixel with no resampling.

**2MASS (All-Sky atlas), M51.** IBE files are `…/allsky/<yymmdd><n|s>/s<scan>/image/<j|h|k>i<scan><tile>.fits.gz`, 512 × 1024 px at 1″ (8.5′ × 17′), about 1.5 MB gzipped. **J, H and Ks of one image share one grid exactly** (same NAXIS, CRVAL, CRPIX, CROTA2). M51's centre lies in image `980527n` scan 024 tile 0232, at pixel (382, 807), 10 px off the neighbouring scan-023 images. IBE cutouts are **exact copies of the original pixels** (checked pixel by pixel, NaNs included) with CRPIX shifted by whole pixels; a box bigger than the image comes back clipped (16.8′ → 512 × 721 px), the REQ-86 behaviour.

**Spitzer (SEIP).** Mosaics live under `/data/SPITZER/Enhanced/SEIP/images/…`, not IBE: the cutout option is **ignored** there (a 1′ request returned the whole 3.2 MB file), but range requests work. So Spitzer boxes are fetched as rows (REQ-57), like HST mosaics. In regions 50057690-0 and 50058000-0 **IRAC channels 1–4 share one grid exactly** (0.6″, same NAXIS, CRVAL, CRPIX); MIPS 24 µm has its own 2.45″ grid. HDR observations add `-short` IRAC mosaics on the same grid (3.9 s against 104 s) → REQ-89.

**Thumbnails.** IRSA has no preview images. CDS hips2fits draws the box from `CDS/P/allWISE/W1–W4`, `CDS/P/2MASS/J,H,K` and `CDS/P/SPITZER/IRAC1–4, MIPS1` in about 0.5 s (5–10 KB JPEG). `CDS/P/SPITZER/MIPS24` doesn't exist (HTTP 400).

**Download chain on real files** (`19b_irsa_download.py`, M51, 1.5 × 11.2′ = 16.8′ box):

| Images | Output | Fetched | Notes |
|---|---|---|---|
| WISE W1–W4 | 735 × 734 px each, identical CRPIX, M51 at (367, 366) | 1.5–1.9 MB per band (not 67 MB) | 3–10 s each |
| 2MASS J, H, Ks | 512 × 721 px each, identical CRPIX | about 1.1 MB per band | clipped at the image edge, row warns |

All seven pass the compatibility check (REQ-49) and load in siril-cli (exit 0).

**Live search, once SIA was back (09:52; `19_irsa_search.py`, `19c_irsa_live.py`).**
- Columns are the ObsCore names the module reads. Values: `obs_collection` spitzer_seip / wise_allwise / twomass_allsky; `instrument_name` IRAC, MIPS, WISE, 2MASS Survey Camera; bands IRAC1–4, MIPS24, W1–W4, J, H, K. `access_url` is the IBE file for WISE and 2MASS (so the cutout option works) and the `/data/SPITZER/…` file for Spitzer.
- Five test objects, 0.4–22 s per collection (the first query after the outage was slow). NGC 1300 has no Spitzer SEIP data.
- **Spitzer lists four science files per region and band**: `mosaic`, `median_mosaic`, `-short` `mosaic`, `-short` `median_mosaic` → median ones dropped (REQ-94). **All share one `obs_id`** (`50069620.50069620-0.IRAC`), which would have given the same product key and output file name to different files; the file name is now the ID.
- Spitzer rows have **no exposure time or date** (`t_exptime`, `t_min` blank); the saved header's EXPTIME has it (IRAC 268–275 s for M51). So short-frames mosaics are listed after the full-depth one, and 'Select deepest' picks the full-depth one.
- Coverage of large objects by one image: M42 (65′) WISE 65%, Spitzer 40%, 2MASS 6%; NGC 7293 (25′) 2MASS 28%.

**M51 end to end:** search 1.2 s, 16 images in three sets (WISE W1–W4, Spitzer IRAC 1–4 with short frames, 2MASS J-H-Ks). IRAC 1–4: 1680 × 1680 px boxes, identical CRPIX, 33.2 MB each fetched as rows of a 120 MB mosaic (as estimated), 1–6 s; MIPS 24: 412 × 412 px, 2.4 MB. All pass the compatibility check and load in siril-cli. Through the page: the WISE set downloaded as four 593 × 593 px files with identical CRPIX, and CREDITS.txt carries the AllWISE and IRSA statements.

## 20 — ESO module (REQ-90 to REQ-93), 2026-10-12 (`20_eso.py`)

**Access.** ObsCore TAP (`archive.eso.org/tap_obs`) answers in 0.2–1.5 s. Public files download **anonymously** from `dataportal.eso.org/dataPortal/file/<ADP id>` with `Accept-Ranges`. Each row's `access_url` is a DataLink document listing the file, a **SODA cutout service** (`dataPortal/soda/sync`), PDF previews, ancillary files (confidence/weight maps) and progenitors.

**What ESO holds (every image collection, grouped).** Combined products have a blank `dataproduct_subtype`; unmerged multi-chip files say `pawprint`. Pawprint-only: VST-ATLAS (31k), VPHAS+ (29k, incl. Hα), VIMOS, most VISTA epochs, SPHERE. Combined: VISTA tiles (VHS 32k, VVV 29k, VVVX 19k, VMC, VIKING, VIDEO, VISIONS, GCAV, SHARKS, UltraVISTA), VST coadds (KiDS 6.8k averaging 1.4 GB, OMEGACAM_INAF, FDS, ARP_VST, VEGAS), HAWK-I stacks (7.6k), SOFI (PESSTO, ePESSTO+). Also ALMA, APEX bolometer maps, NGTS, ERIS, NACO and VISIR, which aren't searched.

**Pawprints (Q-82).** A SODA cutout of a VST-ATLAS pawprint around NGC 253 came back as 6 CCD pieces (`ESO_CCD_#84` …), each on its own grid. Kept out under REQ-12; with them out, NGC 253, NGC 55 and NGC 300 get no ESO set.

**Cutouts (REQ-92).** `CIRCLE=ra dec r` returns the square of side 2r: 0.05° gave 1054 px at 0.341″ (VHS J, 1 MB, 4.6 s). **No resampling:** CRPIX moves by whole pixels (VHS J 7826.012 → 968.012; HAWK-I 2318.610 → 80.610). VISTA and VST cutouts are Rice tile-compressed with the image in HDU 1 (about 0.8 bytes per pixel, like the files); HAWK-I and SOFI come as plain 32-bit floats in the primary HDU. A box past the edge comes back clipped.

**No shared grids.** VHS Y, J and Ks tiles of one night (179.A-2010(K), MJD 57088.28) have different NAXIS, CRPIX and CRVAL (e.g. CRVAL1 203.74109 vs 203.74058); HAWK-I J, H, Ks and Brγ of one pointing differ too. ESO sets need registration; no Grid letters.

**Previews (REQ-93).** Only PDFs (`previews/v1/files/<id>/preview?format=DOWNLOAD`; PNG/JPEG refused). CDS has sky maps for VHS (`wfau.roe.ac.uk/P/VISTA/VHS/Y,J,H,K`), VIKING, VVV (Z, Y, J; H split bulge/disk; no Ks), UltraVISTA and KiDS (colour maps only). hips2fits draws M83 from the VHS J map in 2.6 s (8.8 KB); outside a survey the image comes back blank (4.2 KB).

**Footprint bug found and fixed.** ESO writes `POLYGON J2000 ra dec …`; the parser read the `2000` of 'J2000' as a coordinate, so every ESO footprint failed the centre test. Frame names are now skipped.

**Search results** (default 3 filters):

| Object | Combined rows → images (REQ-91) | Sets |
|---|---|---|
| M83 | 24 → 21 | HAWK-I J H Ks Brγ (4 pointings per filter, lowest coverage 38%); VHS Y J Ks (100%) |
| NGC 7293 | 3 → 3 | VHS Y J Ks (100%) |
| M42 | 6 → 5 | HAWK-I J H Ks (3%: 7.5′ field on a 66′ nebula) |
| M8 | 109 → 10 | VVV/VVVX Z Y J H Ks |
| NGC 3372 | 19 → 3 | VVVX J H Ks |
| NGC 1365 | 33 → 15 | FDS u g r i (100%); HAWK-I Y J H Ks (100%); SOFI J H Ks (92%) |
| NGC 5128 | 40 → 17 | ARP_VST g r NB659 i (100%); SOFI J H Ks (9%) |
| NGC 104 | 40 → 6 | VMC/VHS Y J Ks (100%) |
| NGC 253, NGC 300 | 0 / 4 → 0 sets | (pawprints only, or 2 filters) |

**Download chain on real files** (M83, 1.5 × 13.8′ = 20.7′ box):

| Images | Output | Fetched | Notes |
|---|---|---|---|
| VHS Y, J, Ks | 3507–3519 × 3638 px | 10–13 MB each, 5–7 s | clipped by about 120 px on one side (M83 sits 1,690 px from the tile edge), warning shown |
| HAWK-I J, H, Ks, Brγ (nearest pointing) | the whole 4458–4590 px stack | 79–84 MB each, 3–5 s | the box is bigger than the 7.5′ field; M83's centre is in a corner of each pointing |

All seven pass the compatibility check (REQ-49) and load in siril-cli (exit 0); star-core repair found no holes (VISTA and HAWK-I saturated cores aren't blank); the credits list the HAWK-I (DOI 34) and VHS (DOI 57) collections. The VHS J box shows the whole galaxy cleanly. One HAWK-I Ks quarter has a **darker background** than the others (per-detector sky level in ESO's own stack), now listed in the fact sheet.

**Hα label (fixed).** The OmegaCAM Hα filter NB_659 (653–665 nm) was labelled '[NII]': the line label took the nearest line to its centre (659 nm), and its band holds both Hα and [NII]. It's now named Hα by filter name (`filters.LINE_FILTERS`), so the line filter's 'Hα' picks it (NGC 5128: 'NB659 Hα'). A rule by passband was rejected because HST's [NII] filter F658N also reaches Hα.

## 21 — CADC collections, mirrors and cutouts (REQ-21, REQ-35), 2026-10-12 (`21_cadc.py`)

**Reachability.** From the home network (Fidium, AS13977) every NRC address (132.246.x) still times out. Over a phone hotspot (Verizon, AS6167) CADC answers in about 1 s. So the block is on the Fidium route, not at CADC. CADC's file service was **unstable during the test**: the same file was "found" and "not found" in turn by `cadc-west-01`, `ws-sf` and the `/data/pub` address over about 10 minutes, and `ws-uv.canfar.net` answered 503 throughout. Downloads are passed on to whichever storage site holds a copy (`ws-sf.canfar.net` or `ws-cadc.canfar.net`), and `ws-cadc` is unreachable from Fidium. **So from home, CADC searches and downloads fail even when CADC is up.**

**TAP.** `https://ws.cadc-ccda.hia-iha.nrc-cnrc.gc.ca/argus` (ObsCore plus the CAOM2 tables). CADC's ObsCore has **no `dataproduct_subtype`** column, and its `facility_name`/`instrument_name` are per observation. Filter names (`energy_bandpassName`), exposure time, pixel size and image size are in `caom2.Plane`. Archive-wide counts come instantly from `caom2.ObsCoreEnumField`. A position search took 7–36 s per object, because TESS adds 30,000–60,000 rows per object; a search limited to the stacked collections took 2–6 s.

**Image collections, whole archive** (calib level: rows):

| Group | Collections | Verdict |
|---|---|---|
| Mirrors of MAST | HST (L1–L3), HSTHLA (L3), JWST (L1–L3), TESS (22 M rows, L1/L2) | exclude (REQ-21); TESS is new to the list |
| Mirror of IRSA | IRIS (IRAS reprocessed); EUCLID.Q1 / EUCLID.DR1 (L4) | IRSA holds Euclid and IRIS, so exclude |
| Single exposures / raw | CFHT L1/L2 (MegaPrime, WIRCam, SITELLE, CFH12K), GEMINI (L1), SUBARU (L1), SUBARUCADC L2 (Suprime-Cam per chip), DAO, OMM, APASS, NEOSSAT, SDSS frames (L2), MACHO | excluded by REQ-12 (not combined) |
| Radio / sub-mm | JCMT, SCUBA-LC, JCMTLS, VLASS, RACS, POSSUM, WALLABY, CGPS, VGPS, BLAST | not pictures in the app's sense; to decide |
| Other | XMM Optical Monitor (L2, 85k) | per-exposure UV/optical frames; to decide |
| **Combined optical / near-IR stacks** | **CFHTMEGAPIPE** (L3, 122k), **CFHTWIRWOLF** (WIRCam stacks, L3, 1.7k), **CFHTTERAPIX** (L3, 1k), **NGVS** (Virgo cluster, L3, 2.6k), **SUBARUCADC L3** (Suprime-Cam stacks, 26k), **LSST.DP1** (Rubin, L3, 2.6k) | the candidates for the CADC module |

**Stacks around test objects** (L3 planes containing the centre):

| Object | What's there |
|---|---|
| M51 | MegaPipe g, r (two generations: 2012–15 `G…` tiles 1.6°, 1.9 GB; 2020 `MegaPipe.276.274` tiles 31′ × 31′, 10000², 0.186″/px, 400 MB). No third filter. |
| NGC 891 | MegaPipe g r z; WIRWOLF J Ks; Suprime-Cam stacks B V g r i |
| M87 | MegaPipe u g r i z **plus Hα (MP9603) and [OIII] (MP9501)**, and a gri composite; NGVS u g r i z (8 tiles each); WIRWOLF H Ks; Suprime-Cam stacks B V Rc Ic g i |
| M42, NGC 7293, M1, M31 | MegaPipe 4–38 planes; WIRWOLF at M42 and NGC 7293 |

MegaPipe's Hα and [OIII] planes have a blank `energy_bandpassName`, so the filter has to be read from the product ID (`.HA.MP9603`, `.OIII.MP9501`). The 2020 MegaPipe tiles of one tile number have the same size in every filter, so they are probably on **one pixel grid** (Grid letters, REQ-60). *To check from the headers.*

**Files and cutouts.** Each MegaPipe plane has a science FITS (400 MB to 1.9 GB), a weight map and a 0.6 MB whole-tile GIF preview. ObsCore's `access_url` is a DataLink record listing a SODA cutout service (`caom2ops/sync`, CIRCLE/POLYGON); during the test it redirected to `cadc-west-01`, which answered "not found". **What worked:** the file locator (`…/raven/files/cadc:CFHTSG/<file>`, or the 303 from `/data/pub/CFHTSG/<file>` with a one-byte Range request) followed by the storage site's `minoc/files/…?SUB=[0][x1:x2,y1:y2]`. A 55 × 55 px box at M51 came back as **20 KB in 2 s**, BITPIX −32, on the original grid (CRPIX moved by whole pixels: 5000 − 3352 = 1648), with FILTER, EXPTIME (3111 s) and PHOTZP (30.0) in the header. Public data needed no login. **Caution:** without a Range header, `/data/pub` sometimes sends the whole file instead of a redirect, so every request needs a byte limit.

**Thumbnails.** CDS has sky maps only for the CFHT Legacy Survey (0.4% of the sky), so hips2fits can't be relied on. CADC's GIF previews show the whole 31′ tile, not the box. A thinned-out cutout (`SUB=[0][x1:x2:26,y1:y2:26]`, about 200 × 200 px, ~160 KB) could not be tested because the file service was flipping between sites.

**Still open:** test the thinned-out thumbnail and the shared MegaPipe grid on a good connection; check CFHTTERAPIX, SUBARUCADC L3 and LSST.DP1 products the same way; confirm from Fidium that `ws-sf.canfar.net` (206.12.122.235) and `cadc-west-01.canfar.net` (206.12.48.216) answer. They are on the 206.12.x range, like `www.canfar.net`, which Fidium reaches. Only `ws-cadc` and the `cadc-ccda` names are on the blocked 132.246.x range, and the TAP search lives there, so a Fidium search still fails.

**Why Fidium can't reach CADC (traced 2026-10-12).** The problem isn't on this Mac or the home network:
- DNS (Pi-hole at 192.168.99.13, then Quad9) returns the correct addresses. Other Canadian government sites (weather.gc.ca, ic.gc.ca, cra-arc.gc.ca, nrc-cnrc.gc.ca) and CANFAR's 206.12.x hosts load normally over Fidium. Only the CADC addresses at 132.246.x (Shared Services Canada, AS25689, prefix 132.246.192.0/19) time out.
- The timeouts are silent drops, not refusals. A Little Snitch deny fails at once. Little Snitch's log and NetBarrier's settings need administrator rights, so they weren't read; Intego's network-security switch is off.
- **Routes differ.** Fidium → Cogent (AS174). For weather.gc.ca, Cogent hands over to **Bell Canada** (142.124.x / 64.230.x) and it works. For 132.246.x, Cogent carries the traffic to **Seattle** (`ccr21.sea02` / `ccr82.sea08`) and hands it to **38.142.50.226**, a Cogent customer interface with no name. Nothing answers after that. Over Verizon, 132.246.x is reached through Bell and works.
- So Cogent's route to NRC's 132.246.192.0/19 goes through a Seattle handoff that drops the traffic (or the return route fails). That's for Fidium/Cogent or CADC/NRC networking to fix: report the trace to Fidium support and to support@canfar.net.

## 22 — CADC reachable from Fidium; registry service lookup (2026-10-15, `curl` plus a re-run of `21_cadc.py`)

Prompted by Dustin Jenkins at CADC, who replied to the report with: use the **registry** for service lookups rather than hostnames, which may move. He pointed at `https://cadc-west-01.canfar.net/reg/resource-caps` and asked which service was wanted.

**The 132.246.x block has cleared.** From the home network (Fidium), `ws.cadc-ccda.hia-iha.nrc-cnrc.gc.ca/argus/capabilities` answered **HTTP 200 in 0.40 s**, and `21_cadc.py` ran start to finish over Fidium, exit 0: M51 returned 39,121 image rows in 9.9 s, the `caom2.ObsCoreEnumField` collection table came back, the stacked-product queries for M51, NGC 891 and M87 matched step 21, and the 55 × 55 px MegaPipe cutout arrived (20,160 B, `NAXIS1/2 = 55`, `CRPIX1 1648.0`, `CRPIX2 -3757.0`, G.MP9401, EXPTIME 3110.756) through `raven`, redirected via `cadc-west-01.canfar.net` and then `ws-cadc.canfar.net` (132.246.217.37) — the same prefix that was dropping traffic on 2026-10-10 to 10-12. So the Seattle handoff traced in step 21 is passing today. Nothing on this Mac changed, so the route can come back; the app must treat an unreachable CADC as an archive timeout (S-32, S-33) rather than an error worth stopping for.

Hosts that answered, all HTTP 200 in 0.17–0.73 s: `cadc-west-01.canfar.net` (206.12.48.216), `cadc-east-01.canfar.net` (199.241.161.228), `ws-uv.canfar.net` (206.12.48.219), `ws-sf.canfar.net` (206.12.122.235), `ws-cadc.canfar.net` (132.246.217.37), `sc2.canfar.net` (132.246.217.14), `ws.cadc-ccda.hia-iha.nrc-cnrc.gc.ca` (132.246.217.29). This closes step 21's open item about `ws-sf` and `cadc-west-01`.

**What the registry gives.** `reg/resource-caps` is a 157-line `ivo://… = <capabilities URL>` list, answering in 0.4 s. The services this app needs:

| Need | Registry id | Capabilities host today |
|---|---|---|
| ObsCore + CAOM2 queries (TAP) | `ivo://cadc.nrc.ca/argus` | `ws.cadc-ccda…` |
| DataLink and SODA cutouts | `ivo://cadc.nrc.ca/caom2ops` | `ws.cadc-ccda…` |
| File locator | `ivo://cadc.nrc.ca/global/raven` | `cadc-west-01.canfar.net` |
| SIA, byte access, target resolver | `ivo://cadc.nrc.ca/sia`, `/data`, `/resolver` | `ws.cadc-ccda…` |

Note what that means for the outage: the registry is **not** a way round a blocked host. Everything except `raven` is named on 132.246.217.29, so a repeat of the Fidium problem would break CADC through the registry too. Its value is that the URLs stop being hardcoded, so a service that moves is followed automatically.

**For the CADC module when it is built:** resolve the service URLs from `reg/resource-caps` at start-up (one request, cached for the session) instead of the `TAP = "https://ws.cadc-ccda…/argus"` constant in `21_cadc.py`, and fall back to the last known URL with a message in the log when the registry itself can't be read.

## 23 — Building the CADC module (REQ-95 to REQ-99), 2026-10-20, over Fidium (`23_cadc_module.py` plus a live run of the module)

The follow-up to CADC (which services the app needs) was answered only by a copy of the earlier reply, so no further advice came; the module follows that reply and resolves its services from the registry (REQ-99).

**Reachability.** Fidium still reaches every CADC host, registry included (`argus` 1.1 s, `reg/resource-caps` 0.4 s). Downloads are passed between `ws-cadc`, `ws-uv` and `ws-sf` from one request to the next, and all three answered.

**Search.** The CAOM2 query (Plane × Observation × Artifact, level 3 science files, three collections) took **2–5 s**: M51 3 images after repeats, NGC 891 17, M87 43, M42 7. Colour sets: NGC 891 MegaCam g r z and Suprime-Cam g V r i; M87 MegaCam u g [OIII] r Hα i z and Suprime-Cam B g V Rc i Ic; M42 MegaCam u r i. Details that shaped the module:
- **The artifact URI names the file's archive, not the collection**: WIRWOLF and MegaPipe files are both `cadc:CFHTSG/…`. Building the address from the collection (`cadc:CFHTWIRWOLF/…`) gets "permission denied".
- MegaPipe Hα planes have a blank filter name and passband bounds of −0.0, not blanks; the filter and passband come from the product ID (`.HA.MP9603`).
- The 2020 MegaPipe tiles have no exposure time in CAOM2 (the file header has `EXPTIME`), so rows show "?".
- `MegaPipe.NNN.MMM` tiles and NGVS tiles (`NGVS+0+0.G`) also appear in CFHTMEGAPIPE; the NGVS collection itself holds the same stacks in several background-subtraction versions, so it isn't searched.
- CAOM2 pixel sizes are written to 12 digits (0.185766207876″); rounded to 4 for the page.

**Shared grids** (headers by one 28,800-byte range request each): every filter of one tile has the same NAXIS, CRVAL, CRPIX and CD: MegaPipe `MegaPipe.053.265` g r z; MegaPipe 2012–15 `G011.035.638+42.345` g r; Suprime-Cam `SCLA_035.556+42.350` V g; WIRWOLF `GW001.035.637+42.346` J Ks. Suprime-Cam's `SCLA.053.265` uses MegaPipe's tile numbers, but its CRVAL1 is written as 35.9431 against MegaPipe's 35.94305518 (0.6 px at that declination), so the two collections aren't treated as one grid.

**Cutouts.** `…/raven/files/<uri>?CIRCLE=ra dec r` is redirected (301, 303) to a storage site's `minoc`, which returns the square of side 2r on the file's own grid: 0.01° gave 389 × 389 px (613 KB, 7–10 s), CRPIX moved by whole pixels. Through the module, M51's MegaPipe g and r boxes (1.5′) both came back 486 × 486 px with the same CRPIX (1864, −3542), so they stack without registration. Thinned cutouts work: `SUB=[0][x0:x1:15,y0:y1:15]` gave 201 × 201 px, 170 KB, about 7 s; M51's whole 13.6′ box as a 155 × 200 thumbnail took 7.1 s (clipped at the tile's top edge) and looks right.

## 24 — How big an HST mosaic file is (S-26, REQ-58), 2026-10-21 (`24_mosaic_sizes.py`)

NGC 976's search showed **404 MB** for each HST mosaic: 4,755 box rows × 21,258 px × 4 bytes, from the rule that a mosaic spans a whole skycell (true of M51). Its files are in fact **6,100 × 5,401 px** (263.9 MB on disk, science and weight arrays of 132 MB each), so the fetch is about 115 MB.

**What sets a mosaic's size.** Science-extension headers of 27 mosaics around six objects, against the box (on the skycell's north-up 0.04″ grid) around the footprints MAST returns at the app's 0.02° radius:

| Object | Mosaic files | Box around **its own** footprint | Box around **every mosaic on its skycell** |
|---|---|---|---|
| NGC 976 | 6,100 × 5,401 | 0.94 × 1.00 | 1.00 × 1.00 |
| NGC 3675 (5 skycells) | 1,786–7,198 wide | 0.99–1.06 | 0.99–1.06 |
| M1 | 13,912 × 10,967 | 0.26–0.90 | 0.90 × 1.00 |
| M51 | 21,258 × 20,668 | 0.21–0.50 | 1.00 × 0.95 |
| M82 (3 skycells) | 4,966–21,953 wide | 0.06–1.02 | 0.75–1.10 |
| NGC 4565 | 19,363 × 18,071 | 0.70–1.00 | 1.00 × 1.00 |

Every mosaic of one skycell (all filters, ACS/WFC, WFC3/UVIS and the fine-grid WFC3/IR) shares one array, sized to **the box around all of their footprints**: NGC 976's UVIS mosaics are 6,100 px wide only because its WFC3/IR F160W mosaic reaches further east. M82's p2551x01y10 is the exception (its IR mosaic has its own 7,297 × 15,735 array; the box is 0.75 × 0.73), and a skycell can be wider than 21,258 px (M82's p2552x16y10 is 21,953).

**For the app:** size the estimate from that box (rows of the cut box inside it, plus the 64-row margin fetch() reads, times its width), falling back to a whole skycell when no footprint can be read.

**Chip gap (NGC 976).** Weight maps sampled by range requests: every UVIS mosaic and single visit has a zero-weight diagonal 28–39 px (1.1–1.6″) wide, about 40″ west of the nucleus. Eleven visits at one orientation narrow it (F350LP, 31 exposures: 28–30 px) but never close it. The Pan-STARRS 2.4′ box (skycell 1773.025, g r i z y) has no blank pixel along it.
