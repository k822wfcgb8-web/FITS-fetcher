# Specification: Multi-Archive Astronomical Image Retriever for Amateur Image Processing

**Version:** 1.22 (CADC choices awaiting review)
**Date:** 2026-10-20
**Status:** All open questions resolved; Q-89–Q-93 (CADC module) were decided while building it and await your review. Remaining *(verify)* items must be checked against archive documentation during implementation.

> **How to read this draft**
> - **REQ-xx** is a requirement taken from your request (or a direct consequence of it).
> - **S-xx** is a requirement I suggested; all were reviewed one by one in v0.9.
> - ✅ approved, ✏️ modified, ❌ denied at the suggestion review (v0.9).
> - **Q-xx** is a question that was raised during drafting; all are resolved (Section 12).
> - Statements about archive interfaces and Python libraries are based on my general knowledge, not on a review of current documentation. They're marked *(verify)* and should be checked before implementation.

---

## 1. Purpose

A cross-platform Python application that lets an amateur astrophotographer search public professional astronomy archives for an object by name, find **calibrated, linear, multi-wavelength imaging data** of that object, and download **only the science image** from each file in a form ready to open in PixInsight or Siril for colour-image processing.

## 2. Scope

### 2.1 In scope
- Archives: **MAST**, **ESO Science Archive**, **IRSA**, and **CADC** (restricted; see REQ-21).
- **REQ-21:** *(Revised in v0.8; replaces the v0.4 removal)* **CADC is supported only for data not available from MAST, ESO or IRSA.** CADC collections that mirror another archive (at least HST and JWST, which MAST holds; *full list to verify*) are never queried, so the same observation never appears twice. This applies even when MAST is not selected. Expected CADC-only sources include CFHT (MegaCam/MegaPipe, WIRCam) and Gemini imaging *(verify)*.
- Imaging data only, broadband and narrowband.
- Objects identified by common name or catalogue designation.
- Planets, Pluto and major moons, searched by name in Hubble and JWST (REQ-78 to REQ-81).

### 2.2 Out of scope (proposed; confirm)
- Spectroscopy, interferometry, time-series light curves, catalogues.
- Image processing itself (stretching, colour combination, deconvolution). That stays in PixInsight/Siril.
- Proprietary (non-public) data and any archive account login. *(Confirmed, Q-01)*

---

## 3. Users and Environment

| Item | Requirement |
|---|---|
| REQ-01 | Written in **Python**. |
| REQ-02 | Runs on **macOS, Linux, and Windows**. |
| REQ-31 | *(Resolved Q-02)* Minimum Python version **3.10**. |
| S-02 ✅ | Uses only pure-Python or widely available wheel dependencies, so no compiler is needed on any platform. |
| REQ-28 | *(Resolved Q-03)* Installed from source with **`pip` or `pipx`** and started with a single command that launches the local web page (REQ-09). No stand-alone app bundles in version 1. |
| S-03 ✅ | Requires an internet connection; the app shows a clear message when an archive is unreachable rather than failing silently. |


---

## 4. User Interface

| Item | Requirement |
|---|---|
| REQ-03 | A **search panel** with user-selectable options for **which archive(s) to search**. |
| S-04 ✅ | Archive selection is a set of checkboxes (any combination, default all four), not a single choice. |
| S-05 ✏️ | Results are grouped **Object → Colour set → Filters**. Each filter row shows its archive and instrument as labels, plus the details in S-21. *(modified at review)* |
| S-06 ✅ | The user selects which results to download: individual filters, or a whole colour set at once. |
| S-07 ✅ | A progress display for searches and downloads, with a Cancel button. |
| S-08 ✅ | A settings panel for output folder, cache location, and download limits. |
| REQ-64 | *(Resolved Q-44)* The settings panel is a **dialog** opened from a **Settings** button in the page header, so the current search and results stay as they are. It holds: output and cache folders; download limits (size warning, parallel downloads per archive, archive timeout); **search defaults** (minimum filters, instrument mixing, "Also show HST mosaics", pixel-scale warning ratio); and **processing defaults** (star-core repair and its size limit, cutout and the box size used when an object's size is unknown). Collection lists stay in the settings file only. |
| REQ-72 | *(Resolved Q-58, after the NGC 3675 Pan-STARRS set was taken for Hubble)* When MAST is ticked, the search panel shows a **tick box for each MAST telescope** in the `mast_collections` setting (Hubble, JWST, Pan-STARRS1), all ticked by default. Only the ticked telescopes are searched; MAST is skipped if none is ticked. The setting's list itself still lives in the settings file only (REQ-64). |
| REQ-73 | *(Resolved Q-58)* Every **set heading and result row names the telescope** as well as the instrument, e.g. `MAST · Pan-STARRS1 · GPC1` or `MAST · Hubble · ACS/WFC`, so the source is clear without opening the details. Folder names (S-29) are unchanged. |
| REQ-74 | *(Resolved Q-59, Q-60)* Each telescope name, **both in the tick boxes and in the results**, is a link that opens a **pop-up fact sheet**: aperture, where it is, years active, the cameras FITS-fetcher uses with their pixel scales, wavelength range, **what artifacts to expect** in its images, and a link to the archive's mission page. |
| REQ-65 | *(Resolved Q-45)* Each folder has a **path box and a Choose… button** that opens the system folder dialog. A typed path is accepted if the folder exists or can be created and is writable. |
| REQ-66 | *(Resolved Q-46)* Changes take effect on **Save**; **Cancel** discards them; **Reset to defaults** fills in the built-in values (still applied only on Save). After saving, any changed search or processing default is applied to the search panel and download bar. A download already running keeps the settings it started with. |
| REQ-27 | *(Resolved Q-05)* Results show a **preview thumbnail** for each image. If the archive supplies one, it is used. If not, the app tries to **create one**, without downloading the full science file: from a small cutout or low-resolution image service where one exists (e.g., an archive cutout service or the CDS hips2fits service; *availability per dataset to verify*). If neither is possible, a placeholder is shown, and a thumbnail is made from the science image once it has been downloaded. Thumbnails are display-only and never saved as science data. |
| REQ-09 | *(Resolved Q-04)* The interface is a **local web page**: the Python program starts a small server on the user's own computer (bound to `localhost` only, not reachable from the network) and opens the search panel in the default web browser. |
| S-36 ✅ | The server picks a free port automatically and shuts down cleanly when the user quits from the page or closes the terminal. |


---

## 5. Object Search

| Item | Requirement |
|---|---|
| REQ-04 | Objects can be searched by **common name** (e.g., "Orion Nebula", "Whirlpool Galaxy"). |
| REQ-05 | Objects can be searched by **major catalogue designation**: Messier, NGC, IC, "etc." |
| S-09 ✅ | Names are resolved to coordinates using a standard name-resolution service (e.g., CDS Sesame via `astropy`'s `SkyCoord.from_name`) *(verify behaviour for common names)*. |
| S-10 ✅ | The resolved coordinates and the resolver's matched identifier are shown to the user before searching, so a wrong match is caught early. |
| S-11 ✅ | The user may also enter **RA/Dec coordinates directly** as a fallback. |
| REQ-18 | *(Resolved Q-07)* When a name could match more than one object, the app **lists the candidates** (identifier, object type, coordinates) and the user picks one before the search runs. |
| REQ-13 | *(Resolved Q-06)* Beyond Messier, NGC and IC, **any designation the name resolver recognises** is accepted; there is no fixed catalogue list and no built-in lookup table in version 1. If the resolver doesn't recognise a name, the user is told so and can enter RA/Dec instead (S-11). |
| REQ-14 | *(Resolved Q-08)* An image counts as covering the object only if its footprint **contains the object's resolved centre coordinates**. Images of a large object that miss its centre are offered separately as off-centre sets (REQ-71). |
| REQ-77 | *(Resolved Q-63, after "Helix Nebula" hung on 2026-10-11 while SIMBAD wasn't answering)* Every SIMBAD query **gives up after 15 s**. Once SIMBAD has failed, the lookup stops asking it and uses **Sesame's position** alone (Sesame has its own mirror and time limit). The object panel then notes that the size is unknown, so whole-object boxes, off-centre sets and the 'Also inside' list aren't available for that search. |
| REQ-78 | *(Resolved Q-64, Q-65, after 'saturn' found only the Saturn Nebula, NGC 7009)* The **planets, Pluto and major moons** are recognised by name, in any case: Mercury to Neptune, Pluto; the Moon; Io, Europa, Ganymede, Callisto; Mimas, Enceladus, Tethys, Dione, Rhea, Titan, Iapetus; Miranda, Ariel, Umbriel, Titania, Oberon; Triton; Charon. The body is **listed first among the candidates** (REQ-18), with the resolver's other matches for the same text after it (e.g. 'saturn': Saturn, then NGC 7009). It is shown as 'Solar System · moves across the sky' instead of coordinates. |
| REQ-79 | *(Resolved Q-66, Q-67)* A planet or moon is searched **by MAST target name, not by position**: every public moving-target image whose target name starts with the body's name ('SATURN', 'SATURN-MAPS', 'SATURN-CENTRE'). Only **Hubble and JWST** are searched; Pan-STARRS is skipped whatever the tick boxes say. Hubble makes no Advanced Products for moving targets, so for planets and moons its **classic products are offered, including drizzled single exposures** (an exception to REQ-15 and REQ-58; Saturn: 1,450 of 1,458 Hubble images are single exposures). Each row's product says 'HST single exposure drz' or 'HST combined …'. Coverage and the object's offset from the image centre aren't shown, and the 'Elsewhere in' and 'Also inside' lists don't apply. |
| REQ-80 | *(Resolved Q-68)* For planets and moons, **a colour set holds the filters of one visit only** (JWST observation, e.g. `jw01247-o301`; Hubble `ipppss`), because the body moves, rotates and changes between visits. Each set shows a **visit chip** with the visit and its date, and its folder name ends in the visit. Sets with the same number of filters are listed newest first. Instrument mixing (REQ-11) mixes instruments within a visit only. |
| REQ-81 | *(Resolved with Q-66)* Planet and moon images are **never cut around the object** (REQ-25): there's no fixed position to cut around. The 'Cut around the object' box is greyed out for them. |
| S-12 ✅ | Search radius is set automatically from the object's apparent size when known, with a manual override. |


---

## 6. Data Selection Rules

### 6.1 Linear data

| Item | Requirement |
|---|---|
| REQ-06 | Only **linear** data are offered for download. |
| REQ-68 | *(Resolved Q-48, Q-49)* **Pan-STARRS images are delivered as a box centred on the object, 1.5× its size** (the default cutout box when the size is unknown), **stitched from as many skycells as needed.** Skycells of one projection cell share one pixel lattice (same projection centre, scale and orientation; offsets in whole pixels; verified for M46), so they join exactly with no resampling, and every filter gets the same box (REQ-60). Each skycell is linearised (REQ-36) before stitching; where skycells overlap, each pixel comes from the skycell it lies deepest inside, falling back to another skycell where that one is blank. For each skycell the app fetches only the part inside the box from the PS1 cutout service (linear 32-bit floats on the same pixel grid) or the whole compressed file, whichever is smaller. If the box crosses a projection-cell boundary, the single skycell containing the object is delivered whole until reprojection (REQ-24) is built. Applies to small objects too (M51: a 13.5′ square instead of a whole 24′ skycell). |
| REQ-36 ✅ | *(Added v1.1)* Products stored with a **non-linear pixel encoding** are converted back to linear values before saving, using the conversion the archive documents. Known case: Pan-STARRS stack images, which I believe store pixels in an asinh-compressed form described by the `BOFFSET` and `BSOFTEN` header keywords *(formula `BOFFSET + BSOFTEN·2·sinh(x / (2.5/ln 10))` confirmed in verification step 06)*. Any product whose encoding can't be linearised is excluded. |
| S-13 ✅ | "Linear" is defined as: calibrated pixel values proportional to detected flux (e.g., counts, electrons/s, MJy/sr, calibrated flux), with no stretch, gamma, histogram transformation, or 8/16-bit display scaling applied. |
| S-14 ✅ | Accepted product levels (initial list, *verify each against archive documentation*): HST drizzled `_drz`/`_drc`; JWST Level 3 `_i2d`; Pan-STARRS stacked images; CFHT MegaPipe stacks (CADC); ESO Phase 3 reduced images (VST/VISTA tiles, HAWK-I stacks); Spitzer post-BCD mosaics; WISE/2MASS atlas images; Euclid calibrated images. |
| REQ-15 | *(Resolved Q-10)* Only **combined products** (drizzled, stacked, co-added, or mosaicked by the archive) are offered. Single calibrated exposures (e.g., HST `_flt`/`_flc`, ZTF single frames) are excluded. |
| REQ-16 | *(Resolved Q-09, inferred from Q-10; please confirm)* **Raw, uncalibrated frames are excluded.** This follows from REQ-15, because raw frames are single exposures. |
| S-15 ✅ | Always excluded **as science data**: JPEG/PNG/TIFF previews, colour composites, press-release images, and any product the archive labels as a preview or quick-look. (Previews may still be shown as display-only thumbnails under REQ-27.) |


### 6.2 Multi-wavelength requirement

| Item | Requirement |
|---|---|
| REQ-07 | Results are offered only when the object has data at **more than one wavelength**, suitable for a colour image. |
| S-16 ✅ | A "wavelength" is a distinct **filter or band** (e.g., HST F435W and F814W count as two; two exposures in the same filter count as one). |
| S-17 ✅ | Each result group shows a "colour readiness" summary, e.g., "3 broadband filters (B, V, I)" or "Hα + [OIII] + [SII] (narrowband)". |
| REQ-10 | *(Resolved Q-11)* The **minimum number of distinct filters** is **user-selectable** in the search panel. Default: **3**. Allowed values: 2 or more. |
| REQ-17 | *(Resolved Q-14)* Every filter in a colour set must **contain the object's centre** (the same rule as REQ-14). No adjustable overlap percentage. |
| REQ-19 | *(Resolved Q-13)* The search panel can restrict results by filter type: **broadband, narrowband, or either**, and optionally by **specific emission lines** (at least Hα, Hβ, [OIII], [SII], [NII]; list to be confirmed against the filters the archives actually carry). |
| REQ-26 | *(Resolved Q-25)* When instrument mixing is on, the app **warns** (but does not block) when the pixel scales in a set differ by more than a set ratio (default 4×, adjustable in settings). |
| REQ-11 | *(Resolved Q-12)* Whether a colour set may **mix instruments or archives** is **user-selectable**. Default: **same instrument only**. When mixing is enabled, each result set lists the pixel scale of every filter so the user can see resolution differences. |
| REQ-52 | *(Resolved Q-30)* A **colour set** is **all qualifying filters from one instrument** for the object; the app does not list separate filter combinations. The user ticks which filters in the set to download (S-06). When instrument mixing is enabled (REQ-11), all qualifying filters from all selected archives and instruments form a single set for the object. A set is shown only if it meets the minimum filter count (REQ-10). |
| REQ-82 | *(Resolved Q-69–Q-71)* Every colour set's heading carries a **colour hint**. (1) Each filter with a **swatch and colour name** from its central wavelength: UV (<380 nm), violet, indigo, blue, cyan, green, yellow, orange, red, deep red (680–750 nm), **far red** (0.75–1 µm), **near-IR** (1–2.5 µm), **thermal IR** (2.5–5 µm), **mid-IR** (>5 µm). Light the eye can't see gets a dashed swatch. (2) **Suggested blue, green and red channels**: *natural colour first*: if the set has visible filters in blue (380–500 nm), green (500–590 nm) and red (590–750 nm), only those are used, by colour, and the other filters are listed as 'not used'. Otherwise all filters are split into **equal thirds by count**, never between filters within 5% in wavelength (F322W2 and F323N share a channel); with only two groups, green is the average of blue and red. A label says natural colour, partly natural (includes UV/infrared), approximate colour (no green filter) or false colour (all infrared/UV). It's a hint, not a rule. |
| REQ-83 | *(Resolved Q-72–Q-74, after MCG-01-26-030 on JWST gave two sets with one image per filter)* Every colour set's heading has a **tick box "All N images"** that ticks **every image listed in the set**, including all images of a filter that has several (REQ-53); unticking it clears them. It shows ticked when all the set's images are ticked, a dash when only some are, and follows ticks made on the rows. The **"Select deepest in every filter"** button stays, but only on sets where a filter has more than one image, since elsewhere it does the same as the tick box. There is no tick box for all sets at once. |
| REQ-84 | *(Resolved Q-75, Q-76, after MCG-01-26-030 (JWST programme 1619) showed two squares per NIRCam image while ESA's MACS J0553.4-3342 picture (VENUS, programme 6882) showed one)* A **JWST NIRCam image whose MAST footprint is two or more separate pieces** gets a chip **"2 modules, gap not covered"**: NIRCam's modules A and B sit side by side with a ~44″ strip between them, and a single pointing never sees it. One footprint piece means other pointings filled the gap (VENUS: two visits, 16 exposures in F444W against 1619's one visit, 8), and such images get no chip. The chip appears on each affected image row and on its set's heading; hovering explains it. |
| REQ-53 | *(Resolved Q-31)* When an archive holds **several combined products in the same filter** (different programmes, pointings or depths), **all of them are listed under that filter's row**, each with its exposure time, observation date and observation ID, and the user chooses which to download. They still count as one wavelength (S-16). Automatic selection is left to the future "best set" feature (Section 11). |


### 6.3 Other filters (suggested)

- **S-18** ✅ Public data only. Proprietary data are hidden.
- **REQ-20:** *(Resolved Q-15)* By default **all wavelength ranges from UV to far-IR** are searched. The user can narrow this with the wavelength-range filter in S-19.
- **S-19** ✅ Optional filters: wavelength range (UV / optical / near-IR / mid-IR / far-IR), date range, minimum exposure time, maximum file size.

---

## 7. Archive Integration

### 7.1 Per-archive access (*verify all; these are planned approaches, not tested*)

| Archive | Likely Python access route | Notes |
|---|---|---|
| MAST | `astroquery.mast` (Observations API) | HST, JWST, Pan-STARRS, GALEX, others. Pan-STARRS images may be served through a separate cutout service. |
| ESO | ObsCore TAP via `pyvo` (`archive.eso.org/tap_obs`); SODA cutouts | Phase 3 reduced products. **Anonymous download of public data confirmed** (verification step 20). See REQ-90–REQ-93. |
| IRSA | `astroquery.ipac.irsa` / IVOA SIA via `pyvo` | Spitzer, WISE, 2MASS, Herschel, Euclid, ZTF. |
| CADC | CAOM2 tables on CADC's TAP service via `pyvo`; cutouts from its file service | **Non-mirrored stacks only** (REQ-21): MegaPipe, WIRWOLF and Suprime-Cam stacks (REQ-95). Anonymous download of public data confirmed (verification steps 21, 23). Service addresses from CADC's registry (REQ-99). |

- **S-20** ✅ Each archive is a separate, pluggable module behind a common interface, so archives can be added, removed, or fixed independently when an archive changes its API.

### 7.2 Avoiding duplicate data
- **REQ-55:** *(Resolved Q-33)* Within MAST, Hubble data are taken **only from the `HST` collection** (standard pipeline products). The `HLA` and `HLSP` collections, which reprocess or re-combine the same observations, are not queried, so each Hubble observation appears once.
- **REQ-56:** *(Resolved Q-34)* At IRSA, only **mission pipeline collections** are used (initially `spitzer_seip`, `wise_allwise`, `twomass_allsky`; list kept in configuration). Community re-reductions of the same data (e.g. SINGS, LVL, SIMLA, DustPedia, z0MGS, unWISE) are not queried. Herschel is not offered in version 1, because IRSA holds only community Herschel products and the Herschel pipeline archive (ESA) is out of scope. IRSA is queried through its **SIA image service**, because its ObsCore table omits Spitzer.
- **REQ-58:** *(Resolved Q-38)* Within the `HST` collection (REQ-55), MAST holds the same exposures three times: classic pipeline products (`_drc`/`_drz` per visit), Hubble Advanced Products **single-visit** images (`hst_<prop>_<visit>_…`, aligned to Gaia) and HAP **multi-visit mosaics** (`hst_skycell-…_all`, every visit in one image on a fixed sky grid). The app offers:
  - **Single-visit HAP images by default.**
  - A search-panel switch, **"Also show HST mosaics"** (off by default), that adds the multi-visit mosaics. A mosaic is always delivered **cut around the object**: the same centred pixel box is cut from every filter, so the filters stay pixel-aligned without resampling (verification showed all mosaics of a skycell share one grid). Only the rows of the box are downloaded (REQ-57). The box is 2× the object's size (REQ-25), or a default size when the size is unknown. Objects larger than a skycell (about 14′) or lying across a skycell boundary are cut off at the mosaic edge; the app warns when this happens.
  - **Classic pipeline products are never shown.**
- **REQ-85:** *(Resolved Q-77)* IRSA images (Spitzer mosaics, WISE atlas tiles, 2MASS atlas images) are delivered as a **box centred on the object, 1.5× its size** (the default cutout box when the size is unknown), the same rule as Pan-STARRS (REQ-68). The box is cut **on the original pixel grid, with no resampling**, so the bands of one tile or mosaic get the same box and stack pixel-for-pixel (REQ-60): WISE and 2MASS boxes by **IRSA's cutout service**, Spitzer boxes by fetching only the box's rows (REQ-57), because Spitzer mosaics are served outside that service (verification step 19). The 'Cut around the object' option doesn't change IRSA boxes. Thumbnails come from CDS hips2fits, drawn from each survey's own sky map (REQ-27).
- **REQ-86:** *(Resolved Q-78)* When the box runs past the edge of the image holding the object's centre (2MASS images are 8.5′ × 17′; WISE tiles 1.56°), the app delivers **the part of the box that image covers**. Coverage (REQ-69) shows how much of the object is in it. Joining neighbouring images waits for reprojection (REQ-24), because they aren't on one pixel grid.
- **REQ-87:** *(Resolved Q-79)* IRSA gets **telescope tick boxes** like MAST (REQ-72): one per telescope in the `irsa_collections` setting (Spitzer, WISE, 2MASS), all ticked by default; IRSA is skipped if none is ticked. Each telescope is named on set headings and rows (REQ-73) and links to a fact sheet with artifacts to expect (REQ-74).
- **REQ-88:** *(Resolved Q-80)* IRSA images take **no part in off-centre sets (REQ-71) or the 'Also inside' list (REQ-70)**: WISE and 2MASS are all-sky survey tiles, like Pan-STARRS. Spitzer may be added later if results look thin. IRSA is also not searched for planets and moons (REQ-79).
- **REQ-90:** *(Resolved Q-82, Q-85, Q-87)* ESO is searched through its **ObsCore table**, for **combined products only** (`dataproduct_subtype` blank; pawprints excluded by REQ-12) that are already public, and only if the footprint contains the object's centre (REQ-14). `calib_level` isn't used (every ESO image says 2). ESO gets **telescope tick boxes** like MAST and IRSA (REQ-72, REQ-87), all ticked by default, from the `eso_telescopes` setting: **VISTA** (VIRCAM tiles), **VST** (OmegaCAM combined images), **VLT** (HAWK-I stacks) and **NTT** (SOFI stacks), each with a fact sheet (REQ-74). ALMA, APEX, NGTS, SPHERE and other instruments are never searched. Rows name the telescope (e.g. `ESO · VLT · HAWK-I`); the details name the ESO data collection (e.g. VHS, KiDS), which is also written to the header (`FFSURVEY`) and used for the credits: the ESO programme statement plus the collection's DOI. ESO takes no part in off-centre sets (REQ-71) or the 'Also inside' list (REQ-70), and isn't searched for planets and moons (REQ-79). No two ESO filters share a pixel grid (VHS J, Y and Ks of one night differ slightly), so ESO images get no Grid letter (REQ-60).
- **REQ-91:** *(Resolved Q-86, after M8 returned 80 VVV Ks tiles)* **Repeat epochs are dropped**: repeats only matter for variability and photometry. Per data collection, instrument and filter, only the **deepest image of each pointing** is offered (ESO's 5σ limiting magnitude, else the exposure time). Images whose centres lie further apart than a tenth of the field (at least 1′) are different pointings and are all listed (REQ-53), e.g. HAWK-I's four pointings around M83. A different collection (VVV and VVVX) keeps its own deepest image.
- **REQ-92:** *(Resolved Q-83)* ESO images are delivered as a **box centred on the object, 1.5× its size**, the Pan-STARRS and IRSA rule (REQ-68, REQ-85), cut by **ESO's SODA cutout service on the file's own pixel grid with no resampling** (CRPIX moves by whole pixels; verification step 20). Whole files are 150–230 MB (VISTA tiles) to about 1.4 GB (KiDS). A box past the image edge is clipped, with coverage showing what's missing (REQ-86). The 'Cut around the object' option doesn't change ESO boxes.
- **REQ-93:** *(Resolved Q-84)* ESO's own previews are PDFs only, so thumbnails come from **CDS hips2fits, drawn from the survey's own sky map** where one exists (VHS, VIKING, VVV in Z/Y/J, UltraVISTA, KiDS colour maps). Otherwise the row shows the placeholder, and a thumbnail is made from the image once it's downloaded (REQ-27).
- **REQ-89:** *(Resolved Q-81)* Spitzer IRAC **'short frames' mosaics** (from the short exposures of high-dynamic-range observations; e.g. 3.9 s against 104 s) are **listed under their filter** with the full-depth mosaics (REQ-53), with a **'short frames' chip** explaining that they're shallower but unsaturated. They share the full-depth mosaics' pixel grid, so they get the same Grid letter (REQ-60).
- **REQ-94:** *(Resolved Q-88, after the live IRSA search listed four Spitzer files per band)* Spitzer **median-combined mosaics** (`median_mosaic`, the same exposures combined by median instead of the standard outlier-rejected mean) are **not offered**. Each IRAC band shows the standard mosaic and, where there is one, the short-frames mosaic (REQ-89).
- **REQ-35:** The CADC module keeps an explicit **exclusion list** of mirrored collections. The list lives in configuration, not code, so it can be updated if CADC adds new mirrors. *(Checked in verification step 21)*: **HST, HSTHLA, JWST and TESS** (MAST) and **IRIS, EUCLID.Q1 and EUCLID.DR1** (IRSA). Excluded collections are never queried, even if a telescope's list names them.
- **REQ-95:** *(Decided at build, Q-89, Q-90; awaiting review)* CADC is searched through its **CAOM2 tables** (ObsCore lacks filters, exposure and pixel size) for **public calibration-level-3 images** whose footprint contains the object's centre, from three stacked collections: **MegaPipe** (CFHTMEGAPIPE, MegaCam u g r i z, Hα, [OIII]), **WIRWOLF** (CFHTWIRWOLF, WIRCam J H Ks) and **CADC's Suprime-Cam stacks** (SUBARUCADC level 3; level 2 is single exposures, excluded by REQ-12). CADC gets **telescope tick boxes** like the other archives, from the `cadc_telescopes` setting: **CFHT** (MegaCam and WIRCam) and **Subaru** (Suprime-Cam), each with a fact sheet (REQ-74). Rows read e.g. `CADC · CFHT · MegaCam`; the CADC collection is in the details, the header (`FFSURVEY`) and the credits (observatory statement, MegaPipe paper, CADC acknowledgement). Not searched in version 1: NGVS (its stacks are also in MegaPipe as `NGVS±…` tiles, in several background-subtraction variants), CFHTTERAPIX and LSST.DP1 (small; untested), radio and sub-mm collections and XMM's optical monitor (not pictures in the app's sense). MegaCam's wide **gri** filter is dropped: it's a luminance filter, not a colour channel. No off-centre sets, 'Also inside' list or planets (as REQ-88, REQ-90).
- **REQ-96:** *(Decided at build, Q-91; awaiting review)* **Repeats are dropped as for ESO (REQ-91)**: per CADC collection and filter, only the deepest image of each pointing is offered (CADC's limiting magnitude, else exposure time). MegaPipe's two r filters (MP9601, MP9602) and two i filters count as one filter. Old 1.6° MegaPipe tiles and the newer 31′ tiles are listed together when their centres differ by more than a tenth of the field.
- **REQ-97:** *(Decided at build, Q-92; awaiting review)* CADC images are delivered as a **box centred on the object, 1.5× its size** (REQ-68, REQ-85, REQ-92), cut by **CADC's file service (`CIRCLE`) on the file's own pixel grid with no resampling** (CRPIX moves by whole pixels; verification step 23). All filters of one tile (MegaPipe, WIRWOLF, Suprime-Cam stack, NGVS-in-MegaPipe) share one pixel grid, so they get the **same box and a Grid letter** (REQ-60). A box past the image edge is clipped (REQ-86).
- **REQ-98:** *(Decided at build, Q-93; awaiting review)* CADC's previews show a whole tile and CDS has sky maps for only 0.4% of its sky, so the app **makes its own thumbnail** of the box (REQ-27): the file's header, then every n-th pixel of the box from CADC's file service (about 200 × 200 px, 170 KB, 5–7 s), drawn by the local server when the row scrolls into view and kept for the session. If that fails the placeholder is shown.
- **REQ-99:** *(From CADC, verification step 22)* CADC's service addresses come from its **registry** (`reg/resource-caps`), read once per session, so a service that moves is followed; if the registry can't be read, the last known addresses are used and the log says so. An unreachable CADC is an archive timeout or failure like any other (S-32, S-33).

### 7.3 Result metadata to display (suggested)
- **S-21** ✏️ For each result, the **main row** shows: filter, central wavelength, broadband/narrowband flag, archive + instrument, exposure time, pixel scale, estimated download size. A **click-to-expand details view** shows: telescope, bandwidth, observation date, image dimensions, sky coverage of the object, data product level. *(modified at review)*
- **REQ-69:** *(Resolved Q-50)* Each image row shows **how much of the object the image covers** (e.g. "covers 51% of M 46"), measured as the fraction of the object's disc (its apparent size from the resolver) inside the image footprint; for a stitched or cut image, of the delivered image. Each colour set shows its lowest coverage (taking the best image in each filter), so sets that show the whole object stand out. When the object's size is unknown, coverage shows "—". This moves S-21's "sky coverage of the object" from the details view to the main row.
- **REQ-70:** *(Resolved Q-51)* For an object whose size is known, the search also lists **other objects with colour sets inside it**: images that overlap the object but miss its centre, with at least the minimum number of filters (REQ-10) per instrument. *(Resolved Q-52)* The archives' target names are **identified with SIMBAD**: spellings and aliases merge into one entry per object (listing each instrument's filters), the searched object's own pointings and unknown labels are dropped, and an unknown name whose images point at a listed object joins it. Example for M46: NGC 2438 (WFPC2, 4 filters) and OH 231.8+04.2 (WFC3/IR and WFPC2, 4 filters each); M51 goes from 18 archive names to 4 objects. Each has a **Search** button that searches that object. Survey tiles (Pan-STARRS) are not listed. The search area for this list is capped (see implementation notes) so very large objects stay fast.
- **REQ-71:** *(Resolved Q-53–Q-57, after the M35 search returned only the Pan-STARRS set; verification step 16)* For an object whose size is known, the search also offers **off-centre colour sets**: images that miss the object's centre but where **at least the minimum number of filters (REQ-10) on one pixel grid** (REQ-60: HST single-visit images of one visit and detector, HST mosaics of one skycell) **share an area** inside the object's disc. Groups that need registration (different visits or pointings, JWST) are not offered (Q-53).
  - **Mosaics:** off-centre sets always consider HST multi-visit mosaics, whatever the "Also show HST mosaics" switch says; the switch keeps its meaning for the normal results (Q-54).
  - **Area delivered:** every image of a set is cut to the **same pixel box enclosing the area all its filters cover**, so the filters stay pixel-aligned without resampling. Where that area is tilted in the image, its corners stay blank in every filter (M35 WFC3/UVIS: 49%), rather than cutting to the largest rectangle inside it, which would lose about half the data (Q-55, Q-57). Mosaics are fetched only for the rows of the box (REQ-57); single-visit images are fetched whole and cut. The "cut around the object" option doesn't apply to these sets.
  - **Placement:** a section **"Elsewhere in <object>"** below the normal sets, each set labelled with its distance and compass direction from the centre, the shared area in arcmin² and its coverage of the object (REQ-69) (Q-56).
  - **Search area:** the object's disc, capped at 15′ radius like REQ-70 (same query, run once) (Q-56).
  - **Duplicates:** the same sky appears in each visit's images and again in every skycell mosaic holding them. A set is dropped when another set from the same instrument(s) covers at least 80% of its area with the same filters or more and is deeper (or as deep and larger). Shared areas under 0.25 arcmin² (slivers where a skycell edge clips a mosaic) are dropped. Instrument mixing (REQ-11) and the filter-type and emission-line restrictions (REQ-19) apply as for normal sets.
  - Example, M35: 6 sets, e.g. ACS/WFC F502N, F555W, F606W, F658N 4.3′ NW (2.9 arcmin², from a mosaic) and WFC3/UVIS F555W, F606W, F814W 5.9′ SW (7.4 arcmin², one visit).
- **REQ-59:** *(Resolved Q-39)* The details view also shows the **image centre** as the archive reports it, in decimal degrees and sexagesimal (e.g. `RA 202.46741° (13h 29m 52.18s), Dec +47.19999° (+47° 12′ 00.0″)`), and **how far the object lies from that centre** (″ under 1′, otherwise ′). For an HST mosaic it is labelled *mosaic centre*, because the delivered file is cut around the object.
- **REQ-60:** *(Resolved Q-40)* Within a colour set, images in **two or more filters that share one pixel grid** are marked as a matched group, so the user can see without opening the details which images stack pixel-for-pixel with no registration (PixInsight, Siril). Each group gets a letter and colour (*Grid A*, *Grid B* …): a coloured bar on the row's left edge, a chip under the filter name, and a legend line under the set name listing its filters, with a **Select** button that ticks the whole group. Only grids confirmed in verification step 12 are marked: HST single-visit images from the same visit and detector, HST mosaics from the same skycell, and Pan-STARRS stacks from the same skycell. JWST and different-visit images are not marked, since they need registration.

---

## 8. Download and Science-Image Extraction

| Item | Requirement |
|---|---|
| REQ-08 | If a file contains data other than the science image (calibration arrays, error/weight maps, data-quality masks, instrument tables), **only the science image is extracted**. |
| S-22 ✅ | The output is a **single-image FITS file** (one HDU) containing the science array as **32-bit float**, with the original header keywords that matter kept: WCS (celestial coordinates), filter, instrument, telescope, exposure time, date, units, and object name. |
| S-23 ✅ | Each archive/instrument module defines exactly which extension is the science image (e.g., `SCI` in HST/JWST files). |
| REQ-32 | *(Resolved Q-20)* Weight, exposure, error and data-quality maps are **never saved**. Only the science image is written. |
| REQ-33 | *(Resolved Q-21)* Output format is **FITS only**. |
| REQ-22 | *(Resolved Q-19)* **NaN (blank) pixels are always replaced with 0** in the saved file. When reprojection or cutouts are used (REQ-24, REQ-25), the replacement happens **last**, so zeros are never interpolated into real data. Note: in background-subtracted images, 0 can also be a genuine sky value, so replaced pixels can't be told apart afterwards. |
| REQ-23 | *(Resolved Q-17)* The **original archive file is deleted** once the science image has been extracted and saved successfully. If extraction fails, the original is kept and the error is logged. Because the manifest (S-30) was denied, the **source URL and download date are written into the saved FITS header** (as `HISTORY` or custom keywords), so the original can be downloaded again. Where only the science extension is fetched (REQ-57), no original file is stored, so there is nothing to delete. |
| REQ-12 | *(Resolved Q-18)* For cameras with multiple detector chips, **only products the archive has already combined into a single image** (tiles, stacks, drizzled mosaics) are offered. Unmerged multi-chip files (e.g., VISTA "pawprints", single OmegaCAM exposures) are excluded in version 1. *(Confirmed for ESO with Q-82: most ESO optical data (VST-ATLAS, VPHAS+, VIMOS) are pawprints only, so ESO is mainly near-IR; pawprints can return once reprojection (REQ-24) can join their chips.)* |
| REQ-57 | *(Resolved Q-36)* Where the archive supports **partial (HTTP range) reads**, the app fetches **only the science extension** and the header data it needs, not the whole file. Verified for MAST (HST `_drc`/`_drz`, JWST `_i2d`), where the science array is about one third (HST) to one seventh (JWST) of the file. Archives that don't support partial reads, and single-image files, are downloaded whole. Estimated sizes (S-26) reflect what will actually be fetched. |


### 8.1 Optional processing aids (suggested; none alter the data's linearity)
- **REQ-24:** *(Resolved Q-22)* Optional **reprojection** of all filters in a set onto a common pixel grid (e.g., with the `reproject` package), so they're already aligned when opened in PixInsight/Siril. Off by default.
- **REQ-29:** *(Resolved Q-26)* Reprojection targets the grid of the **finest-resolution filter** in the set.
- **REQ-25:** *(Resolved Q-22)* Optional **cutout** around the object (e.g., 2× its size) to reduce file size for very large mosaics. Off by default.

### 8.2 Download behaviour (suggested)
- **S-26** ✅ Show total estimated size before download, and warn above a user-set limit (default 5 GB).
- **S-27** ✅ Resume interrupted downloads; skip files already downloaded.
- **REQ-54:** *(Resolved Q-32)* Because originals are deleted (REQ-23), "already downloaded" is judged from the **saved output file**. Each output records the processing settings that produced it (star-core repair on/off and size limit, cutout on/off and size, reprojection on/off and target grid) in its FITS header. A file is skipped only if an output with the same name exists **and** its recorded settings match the current ones; otherwise the product is downloaded and processed again, replacing the old output.
- **S-28** ✅ Limit parallel downloads per archive (default 3, adjustable in settings) to avoid overloading archive servers.
- **REQ-61:** *(Resolved Q-41)* The processing options for a download (star-core repair, cutout, and later reprojection) are **tick boxes in the download bar** next to the Download button, pre-set from the saved settings. Changing them affects that download only; the saved defaults stay in the settings panel.
- **REQ-62:** *(Resolved Q-42)* Download progress is shown **in each selected result row** (waiting, downloading with percentage, processing, saved, skipped, failed with the reason), with an **overall progress bar and a Cancel button** in the download bar.
- **REQ-63:** *(Resolved Q-43)* When a download batch finishes, the app shows a **summary** (files saved, skipped and failed, and the output folder) with an **Open folder** button that opens the object's folder in the file manager. The folder is not opened automatically.

### 8.3 Saturated star-core repair *(added v1.1)*

Some pipelines blank the centres of saturated stars (as NaN or 0), which shows up as black star cores. The user's PixInsight script **PixelClip.js v1.1** (J. DePasquale, STScI, 2022, adapted from G. Barrere, 2019; GPL v3) fixes this inside PixInsight. The app performs an adapted version of the same repair before saving, so the files open with the cores already filled.

| Item | Requirement |
|---|---|
| REQ-51 | *(Resolved Q-27)* Star-core repair applies to files from **all archives**, not only MAST. |
| REQ-37 | *(Confirmed by Q-28, Q-29; revised by Q-35 after verification)* **Hole detection.** A pixel is a candidate for repair if it is **NaN or exactly 0**. Data-quality flags are not used: verification showed that HST and JWST combined products carry no DQ array, and Pan-STARRS keeps its mask in a separate file while its blanked cores already decode to NaN (verify/FINDINGS.md, steps 05–07). |
| REQ-38 ✅ | **Only enclosed holes are filled.** Candidate pixels are grouped into connected regions. A region is repaired only if (a) it does **not touch the image edge**, (b) it is **fully surrounded by valid pixels**, and (c) its area is **at most a set limit** (default 2,000 pixels, adjustable; default to be tuned on the S-35 test objects; larger holes next to bright stars: see REQ-67). This prevents filling off-detector borders, chip gaps and other large blank areas, which stay blank and are handled by REQ-22. |
| REQ-67 | *(Resolved Q-47, after testing M37 Pan-STARRS i and z)* **Large holes next to bright stars.** Pan-STARRS masks large areas around very bright stars (rectangles up to about 18,000 px in M37), which REQ-38's size limit leaves black. An enclosed hole larger than the REQ-38 limit is still filled if (a) it is **at most a second limit** (default **50,000 px**, adjustable in settings and recorded in the header) and (b) its **edge is bright starlight**: the brightest tenth of the pixels within 3 px of the hole lie at least **25σ above the sky** (sky and σ from a sigma-clipped sample of the image). In M37 this separated star holes (102–523σ) from blank blocks in empty sky and image borders (2–6σ). Holes that don't touch a star, such as thin streaks running away from it, stay black (*stars only* chosen at review); they can be fixed in PixInsight (e.g. PixelClip or CloneStamp). |
| REQ-39 ✅ | **Fill method.** Holes are filled from the rim inward, one layer at a time: in each pass, every hole pixel touching at least one valid pixel (8-neighbour) is set to the mean of its valid neighbours, using values from the previous pass. This keeps PixelClip's "mean of nearest valid neighbours" approach but fills symmetrically, instead of in raster order (which in the original weights the fill toward the upper-left rim). |
| REQ-40 ✅ | **No threshold in pixel units.** Unlike PixelClip, the app does not use a brightness threshold. PixelClip's 0.0001 threshold applies to PixInsight's 0–1 rescaled image. In the archive's physical units, background-subtracted sky is near or below 0, so a threshold would alter the whole background. |
| REQ-41 ✅ | **Processing order.** Linearisation (REQ-36) → star-core repair → reprojection / cutout (REQ-24, REQ-25) → trimming the blank border (REQ-75) → NaN-to-0 replacement (REQ-22). Repair must come before reprojection, so empty cores aren't interpolated into their surroundings. |
| REQ-75 | *(Resolved Q-61, Q-62, after NGC 3675's WFPC2 pair showed only grey in PixInsight; verification step 17)* Every saved image is **trimmed to the box around its real data** (finite, non-zero pixels). Images on a **shared pixel grid** (REQ-60) are all cut to **one box around every footprint the search found on that grid, plus 16 px**, so they stay pixel-aligned even when downloaded on different days; if real data reaches past that box, the box grows to keep it, and the row and HISTORY say the image now needs registration. A grid image with no usable footprint is not trimmed. **Pan-STARRS boxes (REQ-68) are not trimmed**: they are built to size, and their footprint is a single skycell's. The header records `FFTRIM` and `FFBLANK` (% blank after trimming); files saved before trimming existed are processed again (REQ-54). |
| REQ-76 | *(Resolved Q-61)* When **more than 30%** of a trimmed image is still blank (e.g. WFPC2's L-shaped field), its result row and HISTORY say so, with a PixInsight tip: run Auto Stretch (STF) on a preview inside the data and drag it onto the image. |
| REQ-42 ✅ | **On by default**, with a setting to turn it off. Each repaired file records in its FITS header that repair was applied, the number of regions and pixels filled, and the size limit used (e.g., as `HISTORY` lines). |
| REQ-43 ✅ | **Accuracy note.** Filled cores are a cosmetic estimate (a flat plateau at roughly the rim level), not real measurements. This is acceptable for imaging. The app's documentation states this so filled files aren't used for photometry. |
| REQ-44 ✏️ | **Licensing.** PixelClip.js is GPL v3, the same licence as this project (REQ-34). PixelClip and its authors are credited in the **app documentation only**; file headers do not carry the credit. *(modified at review)* |

### 8.4 File compatibility *(added v1.1)*

| Item | Requirement |
|---|---|
| REQ-45 | *(User requirement, v1.1)* Every saved file **must open directly in PixInsight and Siril**, with no decompression, unpacking or conversion by the user. |
| REQ-46 ✅ | Saved files are **uncompressed FITS**: no gzip (`.gz`), no tile compression (`.fz`, e.g. Rice), no zip/tar archives. Compressed archive downloads are decompressed by the app during extraction. |
| REQ-47 ✅ | The science array is stored as **32-bit float** (`BITPIX = -32`) with **no `BSCALE`/`BZERO` scaling**, so the stored numbers are the actual pixel values. |
| REQ-48 ✅ | Files use the `.fits` extension, which both programs recognise. |
| REQ-49 ✅ | **Compatibility check before saving:** each output is checked automatically for a single image HDU, `BITPIX = -32`, no compression, no scaling keywords, and a valid celestial WCS. A file that fails is not saved, and the reason is logged. |
| REQ-50 ✅ | **Testing:** where Siril is installed, the test suite loads each test output with Siril's command-line version (`siril-cli`; on macOS `/Applications/Siril.app/Contents/MacOS/siril-cli`, scripting confirmed in verification step 10, exit code 0/1 marks success/failure). PixInsight is checked manually, at least once per instrument, because I'm not aware of a simple way to script PixInsight from outside. |

---

## 9. Output Organisation (suggested)

- **S-29** ✏️ Folder structure by **colour set**: `<output>/<Object>/<ColourSet>/<Filter>_<Instrument>_<ObsID>.fits`, where `<ColourSet>` is named from the instrument(s) and filters, e.g. `ACS-WFC_F435W-F555W-F814W`. If the same file belongs to more than one downloaded set, it is copied into each set folder. *(modified at review)*
- ~~**S-30** A **manifest file** (CSV and/or JSON) per object listing every file with its metadata (Section 7.3), source URL, and download date, for provenance and reproducibility.~~ ❌ *(denied at review)*
- **REQ-30:** *(Resolved Q-23)* A plain-text **credits file** per object with the acknowledgement text each archive/mission asks users to include when publishing images.

---

## 10. Non-Functional Requirements (suggested)

- **S-32** ✏️ Search results **stream in**: each archive results appear as soon as that archive responds. Each archive query has a timeout (default 60 s, adjustable); an archive that times out is reported to the user without stopping the others. *(modified at review)*
- **S-33** ✅ All archive errors and timeouts are logged to a log file and shown to the user in plain language.
- **S-34** ✅ Configuration stored in a user settings file in the platform's standard location.
- **REQ-34:** *(Resolved Q-24)* The code is licensed under the **GNU GPL v3**. (Dependencies such as Astropy and astroquery use BSD-style licences, which I believe are compatible with GPL v3; *verify*.)
- **S-35** ✅ Automated tests use a fixed list of test objects with known multi-wavelength coverage. Proposed list (coverage to be confirmed during testing): M42, M51, M16, NGC 7293, NGC 1300, IC 434.

---

## 11. Possible Future Features (not in version 1 unless you say so)

- Batch mode: a list of objects in, all downloads out.
- "Best set" recommendation: automatically pick the deepest, best-overlapping filter set.
- Search history and saved searches.
- Additional archives (e.g., NOIRLab Astro Data Archive, ESA archives for Euclid/Herschel, HEASARC).
- Wavelength-to-colour suggestions (which filter to map to R, G, B).

---

## 12. Question Log (all resolved)

| ID | Topic | Blocking for v1? |
|---|---|---|
| ~~Q-01~~ | Proprietary data: **resolved → public data only, no logins** | — |
| ~~Q-02~~ | Python: **resolved → 3.10+ (REQ-31)** | — |
| ~~Q-03~~ | Distribution: **resolved → pip/pipx from source (REQ-28)** | — |
| ~~Q-04~~ | GUI type: **resolved → local web page (REQ-09)** | — |
| ~~Q-05~~ | Thumbnails: **resolved → archive preview, else generated (REQ-27)** | — |
| ~~Q-06~~ | Catalogues: **resolved → anything the resolver knows (REQ-13)** | — |
| ~~Q-07~~ | Ambiguous names: **resolved → show candidates (REQ-18)** | — |
| ~~Q-08~~ | Coverage: **resolved → must contain object centre (REQ-14)** | — |
| ~~Q-09~~ | Raw frames: **resolved → excluded, inferred (REQ-16)** | — |
| ~~Q-10~~ | Single exposures: **resolved → combined products only (REQ-15)** | — |
| ~~Q-11~~ | Minimum filters: **resolved → user-selectable, default 3 (REQ-10)** | — |
| ~~Q-12~~ | Instrument mixing: **resolved → user-selectable, default same instrument (REQ-11)** | — |
| ~~Q-13~~ | Filter type: **resolved → broad/narrow plus specific lines (REQ-19)** | — |
| ~~Q-14~~ | Filter overlap: **resolved → every filter contains the centre (REQ-17)** | — |
| ~~Q-15~~ | Wavelengths: **resolved → UV to far-IR by default (REQ-20)** | — |
| ~~Q-16~~ | Duplicates: **resolved → CADC kept for non-mirrored data only (REQ-21, REQ-35; revised v0.8)** | — |
| ~~Q-17~~ | Originals: **resolved → deleted after extraction (REQ-23)** | — |
| ~~Q-18~~ | Multi-chip files: **resolved → pre-combined products only (REQ-12)** | — |
| ~~Q-19~~ | NaN pixels: **resolved → always replaced with 0 (REQ-22)** | — |
| ~~Q-20~~ | Weight maps: **resolved → never saved (REQ-32)** | — |
| ~~Q-21~~ | Format: **resolved → FITS only (REQ-33)** | — |
| ~~Q-22~~ | Processing aids: **resolved → both offered, off by default (REQ-24, REQ-25)** | — |
| ~~Q-23~~ | Credits: **resolved → credits file written (REQ-30)** | — |
| ~~Q-24~~ | Licence: **resolved → GPL v3 (REQ-34)** | — |
| ~~Q-25~~ | Resolution mixing: **resolved → warn only (REQ-26)** | — |
| ~~Q-26~~ | Reprojection grid: **resolved → finest resolution (REQ-29)** | — |
| ~~Q-27~~ | Repair scope: **resolved → all archives (REQ-51)** | — |
| ~~Q-28~~ | DQ flags: **resolved → yes, saturated flags are filled (REQ-37); superseded by Q-35** | — |
| ~~Q-29~~ | Zero pixels: **resolved → NaN and zero both count (REQ-37)** | — |
| ~~Q-30~~ | Colour set definition: **resolved → all filters per instrument, user ticks filters (REQ-52)** | — |
| ~~Q-31~~ | Several products per filter: **resolved → list all, user chooses (REQ-53)** | — |
| ~~Q-32~~ | Re-download after settings change: **resolved → reprocess when settings differ (REQ-54)** | — |
| ~~Q-33~~ | Hubble duplicates inside MAST: **resolved → `HST` collection only (REQ-55)** | — |
| ~~Q-34~~ | IRSA duplicates: **resolved → mission pipeline collections only, no Herschel in v1 (REQ-56)** | — |
| ~~Q-35~~ | Hole detection after verification: **resolved → NaN and zero only, no DQ flags (REQ-37 revised)** | — |
| ~~Q-36~~ | Partial downloads: **resolved → science extension only where supported (REQ-57)** | — |
| ~~Q-38~~ | HST product families: **resolved → HAP single-visit by default, switch to add mosaics cut around the object, no classic pipeline (REQ-58)** | — |
| ~~Q-37~~ | Siril test (REQ-50): **resolved → Siril 1.4.4 installed, `siril-cli` scripting confirmed** | — |
| ~~Q-39~~ | Exact position in the details view: **resolved → image centre in degrees and sexagesimal, plus the object's offset from it (REQ-59)** | — |
| ~~Q-40~~ | Marking images that can be superimposed: **resolved → same pixel grid only (HST same visit, HST mosaic skycell, PS1 skycell), coloured edge + chip + legend with a Select button (REQ-60)** | — |
| ~~Q-41~~ | Where download options are chosen: **resolved → tick boxes in the download bar, pre-set from settings (REQ-61)** | — |
| ~~Q-42~~ | Download progress display: **resolved → status in each result row, overall bar and Cancel in the download bar (REQ-62)** | — |
| ~~Q-43~~ | End of a download batch: **resolved → summary with an Open folder button (REQ-63)** | — |
| ~~Q-44~~ | Settings panel placement and contents: **resolved → dialog from the header; folders, download limits, search and processing defaults (REQ-64)** | — |
| ~~Q-45~~ | Choosing folders: **resolved → path box plus Choose… system dialog (REQ-65)** | — |
| ~~Q-46~~ | Saving settings: **resolved → Save / Cancel / Reset to defaults (REQ-66)** | — |
| ~~Q-47~~ | Large masked holes around bright stars: **resolved → second, larger limit (50,000 px) for holes whose edge is bright starlight; streaks not touching the star stay black (REQ-67)** | — |
| ~~Q-48~~ | Pan-STARRS images covering only part of a large object (M46: 51%): **resolved → stitch skycells into one box around the object (REQ-68)** | — |
| ~~Q-49~~ | Size of the Pan-STARRS box: **resolved → 1.5× the object, for all objects (REQ-68)** | — |
| ~~Q-50~~ | Showing coverage of the object: **resolved → percentage on the main row and per set (REQ-69)** | — |
| ~~Q-51~~ | Images of other objects inside a large object: **resolved → listed with a Search button (REQ-70)** | — |
| ~~Q-52~~ | Noisy 'Also inside' list (pointings, spellings, aliases): **resolved → identify target names with SIMBAD (REQ-70)** | — |
| ~~Q-53~~ | M35 returned only Pan-STARRS (the centre rule drops 497 of 506 HST images): **resolved → offer off-centre sets, same pixel grid only (REQ-71)** | — |
| ~~Q-54~~ | Mosaics for off-centre sets: **resolved → always included (REQ-71)** | — |
| ~~Q-55~~ | Area delivered for an off-centre set: **resolved → the area all its filters share (REQ-71)** | — |
| ~~Q-56~~ | Placement and search area: **resolved → own section below the results; disc capped at 15′ (REQ-71)** | — |
| ~~Q-57~~ | Tilted shared area: **resolved → box around it, blank corners kept (REQ-71)** | — |
| ~~Q-58~~ | Which MAST telescope a result comes from (NGC 3675's GPC1 set looked like Hubble): **resolved → telescope tick boxes under MAST (REQ-72) and the telescope named on every set and row (REQ-73)** | — |
| ~~Q-59~~ | Telescope information: **resolved → pop-up fact sheet including artifacts to expect (REQ-74)** | — |
| ~~Q-60~~ | Where telescope names link to it: **resolved → tick boxes and results (REQ-74)** | — |
| ~~Q-61~~ | Mostly blank images (NGC 3675 WFPC2: 56% blank, so STF's median and spread were 0): **resolved → trim to the data and warn above 30% blank (REQ-75, REQ-76)** | — |
| ~~Q-62~~ | Trimming images on a shared grid: **resolved → one box from the grid's archive footprints plus 16 px (REQ-75)** | — |
| ~~Q-63~~ | Name lookup hung while SIMBAD wasn't answering: **resolved → 15 s limit, then Sesame's position with a note (REQ-77)** | — |
| ~~Q-64~~ | Which Solar System bodies ('saturn' found NGC 7009, not the planet imaged by JWST programme 1247): **resolved → planets, Pluto and major moons, a fixed list (REQ-78)** | — |
| ~~Q-65~~ | What 'saturn' lists: **resolved → the planet first, the Saturn Nebula still below it (REQ-78)** | — |
| ~~Q-66~~ | Which telescopes for planets: **resolved → Hubble and JWST only, no Pan-STARRS (REQ-79)** | — |
| ~~Q-67~~ | Hubble's planet images are almost all single exposures, excluded by REQ-15: **resolved → offered for planets and moons, marked as single exposures (REQ-79)** | — |
| ~~Q-68~~ | Which images form one planet colour set: **resolved → one visit only (REQ-80)** | — |
| ~~Q-69~~ | How to show which part of the spectrum a set covers: **resolved → swatch and colour name per filter, plus suggested RGB channels (REQ-82)** | — |
| ~~Q-70~~ | Colour names: **resolved → the visible names plus far red, near-IR, thermal IR and mid-IR (REQ-82)** | — |
| ~~Q-71~~ | How to pick the RGB channels: **resolved → natural colour first; otherwise equal thirds keeping close filters together, after splitting at the largest jumps gave 1/9/6 filters on M51's NIRCam set (REQ-82)** | — |
| ~~Q-72~~ | Where a 'download all' tick box goes: **resolved → one on each set heading, none for all sets (REQ-83)** | — |
| ~~Q-73~~ | What it ticks where a filter has several images: **resolved → every image in the set (REQ-83)** | — |
| ~~Q-74~~ | The 'Select deepest in every filter' button: **resolved → kept, but only on sets with several images in a filter (REQ-83)** | — |
| ~~Q-75~~ | Where the module-gap chip goes: **resolved → image row and set heading (REQ-84)** | — |
| ~~Q-76~~ | Also mark images where the gap was filled: **resolved → no, gap only (REQ-84)** | — |
| ~~Q-77~~ | IRSA image size (WISE tiles 1.56°, about 67 MB per band): **resolved → box 1.5× the object, cut on the original grid (REQ-85)** | — |
| ~~Q-78~~ | Objects bigger than one IRSA image: **resolved → deliver the part the centre image covers, with coverage shown (REQ-86)** | — |
| ~~Q-79~~ | IRSA telescopes: **resolved → tick boxes and fact sheets like MAST (REQ-87)** | — |
| ~~Q-80~~ | IRSA in off-centre sets and 'Also inside': **resolved → not for IRSA (REQ-88)** | — |
| ~~Q-81~~ | Spitzer 'short frames' IRAC mosaics: **resolved → listed under the same filter with a chip (REQ-89)** | — |
| ~~Q-82~~ | ESO pawprints (most of ESO's optical data, incl. VST-ATLAS and VPHAS+ Hα): **resolved → keep excluded under REQ-12 until reprojection (REQ-12, REQ-90)** | — |
| ~~Q-83~~ | ESO delivery (VISTA tiles 150–230 MB, KiDS about 1.4 GB): **resolved → box 1.5× the object from ESO's cutout service (REQ-92)** | — |
| ~~Q-84~~ | ESO thumbnails (previews are PDF only): **resolved → survey sky map where CDS has one, else placeholder (REQ-93)** | — |
| ~~Q-85~~ | ESO telescopes: **resolved → tick boxes for VISTA, VST, VLT (HAWK-I) and NTT (SOFI) (REQ-90)** | — |
| ~~Q-86~~ | Repeat epochs (M8: 80 VVV Ks tiles): **resolved → not wanted (no photometry); deepest image per pointing and collection (REQ-91)** | — |
| ~~Q-87~~ | ESO in off-centre sets and 'Also inside': **resolved → neither (REQ-90)** | — |
| ~~Q-88~~ | Spitzer median-combined mosaics: **resolved → not offered (REQ-94)** | — |
| Q-89 | CADC collections: **decided at build → MegaPipe, WIRWOLF, Suprime-Cam level-3 stacks; not NGVS, TERAPIX, LSST.DP1, radio, XMM-OM (REQ-95)** | awaiting review |
| Q-90 | CADC telescopes: **decided at build → tick boxes for CFHT and Subaru, with fact sheets (REQ-95)** | awaiting review |
| Q-91 | CADC repeats (MegaPipe's two tile generations and filter versions): **decided at build → deepest per pointing, the ESO rule (REQ-96)** | awaiting review |
| Q-92 | CADC delivery: **decided at build → box 1.5× the object from CADC's cutout, on the file's grid (REQ-97)** | awaiting review |
| Q-93 | CADC thumbnails: **decided at build → made by the app from a thinned cutout (REQ-98)** | awaiting review |

---

## Revision History

| Version | Date | Changes |
|---|---|---|
| 0.1 | 2026-10-10 | Initial draft from user requirements; suggestions and questions added. |
| 0.2 | 2026-10-10 | Resolved Q-04 (local web page), Q-11 (min filters user-selectable), Q-12 (mixing user-selectable), Q-18 (pre-combined only). Added REQ-09–12, S-36, Q-25. |
| 0.3 | 2026-10-10 | Resolved Q-06, Q-08, Q-10, Q-14; Q-09 resolved by inference from Q-10. Added REQ-13–17. Fixed table layout from v0.2. All blocking questions now resolved. |
| 0.4 | 2026-10-10 | Resolved Q-07, Q-13, Q-15, Q-16. Added REQ-18–21. **CADC removed from scope.** |
| 0.5 | 2026-10-10 | Resolved Q-17, Q-19, Q-22, Q-25. Added REQ-22–26 (S-24/S-25 promoted to REQ-24/25). Added Q-26. |
| 0.6 | 2026-10-10 | Resolved Q-03, Q-05, Q-23, Q-26. Added REQ-27–30 (S-31 promoted to REQ-30). |
| 0.7 | 2026-10-10 | Resolved Q-01, Q-02, Q-20, Q-21, Q-24. Added REQ-31–34. All questions resolved. |
| 0.8 | 2026-10-10 | CADC restored for data not covered by MAST, ESO or IRSA (REQ-21 revised, REQ-35 added). |
| 0.9 | 2026-10-10 | Suggestion review: S-02–S-36 approved, except S-05, S-21, S-29, S-32 modified and S-30 denied. REQ-23 updated to record the source URL in the FITS header. |
| 1.0 | 2026-10-10 | All questions and suggestions resolved. Specification approved. |
| 1.1 | 2026-10-10 | Added REQ-36 (linearise non-linear encodings), Section 8.3 star-core repair adapted from PixelClip.js (REQ-37–44), Section 8.4 file compatibility (REQ-45–50). Added and resolved Q-27–Q-29 (REQ-51). |
| 1.1a | 2026-10-10 | REQ-36–50 reviewed: all approved except REQ-44 modified (credit in documentation only). Specification approved. |
| 1.2 | 2026-10-10 | Renamed to `REQUIREMENTS.md`. Added and resolved Q-30–Q-32: colour set definition (REQ-52), several products per filter (REQ-53), re-processing when settings change (REQ-54). Added and resolved Q-33: Hubble data from the `HST` collection only (REQ-55). Added and resolved Q-34: IRSA pipeline collections only (REQ-56). |
| 1.3 | 2026-10-10 | After verification steps 01–09: REQ-37 revised (NaN/zero only, Q-35); REQ-57 added (science-extension-only downloads, Q-36); REQ-23 note added; Q-37 opened and resolved (Siril installed, `siril-cli` scriptable). REQ-36 formula confirmed. |
| 1.4 | 2026-10-10 | Added and resolved Q-38: HST product families (REQ-58). |
| 1.5 | 2026-10-10 | Added and resolved Q-39: image centre and object offset in the details view (REQ-59). |
| 1.6 | 2026-10-10 | Added and resolved Q-40: matched-grid marking (REQ-60), after verification step 12. |
| 1.7 | 2026-10-10 | Added and resolved Q-41–Q-43: download options in the download bar (REQ-61), per-row progress (REQ-62), end-of-batch summary with Open folder (REQ-63). Build order: download and processing first with MAST only; reprojection (REQ-24/29) in a later build. |
| 1.8 | 2026-10-10 | Added and resolved Q-44–Q-46: settings dialog (REQ-64), folder choice (REQ-65), saving behaviour (REQ-66). |
| 1.9 | 2026-10-10 | Added and resolved Q-47: larger repair limit for holes next to bright stars (REQ-67), after M37 Pan-STARRS i/z showed black masked areas. |
| 1.10 | 2026-10-10 | Added and resolved Q-48–Q-52 after the M46 search: Pan-STARRS box stitched from skycells (REQ-68), coverage shown on each row (REQ-69), objects inside a large object listed (REQ-70). |
| 1.11 | 2026-10-11 | Added and resolved Q-53–Q-57 after the M35 search: off-centre same-grid colour sets in large objects (REQ-71); REQ-14 note. |
| 1.12 | 2026-10-11 | Added and resolved Q-58–Q-60 after the NGC 3675 download: MAST telescope tick boxes (REQ-72), telescope named on sets and rows (REQ-73), telescope fact-sheet pop-ups (REQ-74). |
| 1.13 | 2026-10-11 | Added and resolved Q-61–Q-62 after NGC 3675's WFPC2 pair stretched to grey: trim the blank border (REQ-75), warn when still mostly blank (REQ-76); REQ-41 order updated. |
| 1.14 | 2026-10-11 | Added and resolved Q-63 after a name lookup hung during a SIMBAD outage: 15 s SIMBAD limit with Sesame fallback (REQ-77). |
| 1.15 | 2026-10-11 | Added and resolved Q-64–Q-68 after 'saturn' found only the Saturn Nebula: planets and major moons by name (REQ-78), searched by MAST target name in Hubble and JWST with Hubble single exposures allowed (REQ-79), one visit per colour set (REQ-80), never cut (REQ-81). Scope updated. |
| 1.16 | 2026-10-11 | Added and resolved Q-69–Q-71: colour hint on every set heading, with colour names per filter and suggested RGB channels (REQ-82). |
| 1.17 | 2026-10-11 | Added and resolved Q-72–Q-74: an "All N images" tick box on every set heading (REQ-83). |
| 1.18 | 2026-10-11 | Added and resolved Q-75, Q-76: "2 modules, gap not covered" chip on NIRCam images whose footprint is in separate pieces (REQ-84). |
| 1.19 | 2026-10-12 | Added and resolved Q-77–Q-80 for the IRSA module: box around the object on the original grid (REQ-85), clipped at the image edge (REQ-86), telescope tick boxes and fact sheets (REQ-87), no off-centre or 'Also inside' lists (REQ-88). Added and resolved Q-81: Spitzer short-frame mosaics listed with a chip (REQ-89). |
| 1.20 | 2026-10-12 | Added and resolved Q-82–Q-87 for the ESO module: pawprints stay excluded (REQ-12 note), combined products with telescope tick boxes, fact sheets and DOI credits, no off-centre or 'Also inside' lists (REQ-90), repeat epochs dropped (REQ-91), box around the object from ESO's cutout service (REQ-92), survey sky-map thumbnails (REQ-93). ESO row in 7.1 updated: anonymous download confirmed. |
| 1.20a | 2026-10-12 | OmegaCAM's NB_659 filter labelled Hα (was [NII], the line nearest its centre), so the Hα line filter (REQ-19) finds it. |
| 1.21 | 2026-10-12 | Added and resolved Q-88 after the live IRSA search: Spitzer median-combined mosaics not offered (REQ-94). |
| 1.22 | 2026-10-20 | CADC module built. Exclusion list finalised (REQ-35). Added REQ-95–REQ-98 (decided while building, Q-89–Q-93, awaiting review) and REQ-99 (registry lookup, from CADC's advice). CADC row in 7.1 updated. |
