# Specification: Multi-Archive Astronomical Image Retriever for Amateur Image Processing

**Version:** 1.10 (approved)
**Date:** 2026-10-10
**Status:** All open questions resolved. Remaining *(verify)* items must be checked against archive documentation during implementation.

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
| REQ-14 | *(Resolved Q-08)* An image counts as covering the object only if its footprint **contains the object's resolved centre coordinates**. |
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
| ESO | `astroquery.eso` | Phase 3 reduced products. Confirm whether anonymous download is permitted for public data. |
| IRSA | `astroquery.ipac.irsa` / IVOA SIA via `pyvo` | Spitzer, WISE, 2MASS, Herschel, Euclid, ZTF. |
| CADC | `astroquery.cadc` or `pyvo` TAP queries | **Non-mirrored collections only** (REQ-21): CFHT (incl. MegaPipe), Gemini, others to be confirmed. HST and JWST collections excluded. |

- **S-20** ✅ Each archive is a separate, pluggable module behind a common interface, so archives can be added, removed, or fixed independently when an archive changes its API.

### 7.2 Avoiding duplicate data
- **REQ-55:** *(Resolved Q-33)* Within MAST, Hubble data are taken **only from the `HST` collection** (standard pipeline products). The `HLA` and `HLSP` collections, which reprocess or re-combine the same observations, are not queried, so each Hubble observation appears once.
- **REQ-56:** *(Resolved Q-34)* At IRSA, only **mission pipeline collections** are used (initially `spitzer_seip`, `wise_allwise`, `twomass_allsky`; list kept in configuration). Community re-reductions of the same data (e.g. SINGS, LVL, SIMLA, DustPedia, z0MGS, unWISE) are not queried. Herschel is not offered in version 1, because IRSA holds only community Herschel products and the Herschel pipeline archive (ESA) is out of scope. IRSA is queried through its **SIA image service**, because its ObsCore table omits Spitzer.
- **REQ-58:** *(Resolved Q-38)* Within the `HST` collection (REQ-55), MAST holds the same exposures three times: classic pipeline products (`_drc`/`_drz` per visit), Hubble Advanced Products **single-visit** images (`hst_<prop>_<visit>_…`, aligned to Gaia) and HAP **multi-visit mosaics** (`hst_skycell-…_all`, every visit in one image on a fixed sky grid). The app offers:
  - **Single-visit HAP images by default.**
  - A search-panel switch, **"Also show HST mosaics"** (off by default), that adds the multi-visit mosaics. A mosaic is always delivered **cut around the object**: the same centred pixel box is cut from every filter, so the filters stay pixel-aligned without resampling (verification showed all mosaics of a skycell share one grid). Only the rows of the box are downloaded (REQ-57). The box is 2× the object's size (REQ-25), or a default size when the size is unknown. Objects larger than a skycell (about 14′) or lying across a skycell boundary are cut off at the mosaic edge; the app warns when this happens.
  - **Classic pipeline products are never shown.**
- **REQ-35:** The CADC module keeps an explicit **exclusion list** of mirrored collections (initially HST and JWST). The list lives in configuration, not code, so it can be updated if CADC adds new mirrors. During implementation, the CADC collection list must be checked against MAST, ESO and IRSA holdings to finalise it *(verify)*.

### 7.3 Result metadata to display (suggested)
- **S-21** ✏️ For each result, the **main row** shows: filter, central wavelength, broadband/narrowband flag, archive + instrument, exposure time, pixel scale, estimated download size. A **click-to-expand details view** shows: telescope, bandwidth, observation date, image dimensions, sky coverage of the object, data product level. *(modified at review)*
- **REQ-69:** *(Resolved Q-50)* Each image row shows **how much of the object the image covers** (e.g. "covers 51% of M 46"), measured as the fraction of the object's disc (its apparent size from the resolver) inside the image footprint; for a stitched or cut image, of the delivered image. Each colour set shows its lowest coverage (taking the best image in each filter), so sets that show the whole object stand out. When the object's size is unknown, coverage shows "—". This moves S-21's "sky coverage of the object" from the details view to the main row.
- **REQ-70:** *(Resolved Q-51)* For an object whose size is known, the search also lists **other objects with colour sets inside it**: images that overlap the object but miss its centre, with at least the minimum number of filters (REQ-10) per instrument. *(Resolved Q-52)* The archives' target names are **identified with SIMBAD**: spellings and aliases merge into one entry per object (listing each instrument's filters), the searched object's own pointings and unknown labels are dropped, and an unknown name whose images point at a listed object joins it. Example for M46: NGC 2438 (WFPC2, 4 filters) and OH 231.8+04.2 (WFC3/IR and WFPC2, 4 filters each); M51 goes from 18 archive names to 4 objects. Each has a **Search** button that searches that object. Survey tiles (Pan-STARRS) are not listed. The search area for this list is capped (see implementation notes) so very large objects stay fast.
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
| REQ-12 | *(Resolved Q-18)* For cameras with multiple detector chips, **only products the archive has already combined into a single image** (tiles, stacks, drizzled mosaics) are offered. Unmerged multi-chip files (e.g., VISTA "pawprints", single OmegaCAM exposures) are excluded in version 1. |
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
| REQ-41 ✅ | **Processing order.** Linearisation (REQ-36) → star-core repair → reprojection / cutout (REQ-24, REQ-25) → NaN-to-0 replacement (REQ-22). Repair must come before reprojection, so empty cores aren't interpolated into their surroundings. |
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
