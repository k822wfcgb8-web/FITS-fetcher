# FITS-fetcher

Find calibrated, linear, multi-filter images of an astronomical object in public professional archives, and
download just the science image from each, ready to open in PixInsight or Siril for colour processing.

The full specification is in [REQUIREMENTS.md](REQUIREMENTS.md). Results of checking it against the live
archives are in [verify/FINDINGS.md](verify/FINDINGS.md).

## Status

| Part | State |
|---|---|
| Object lookup (names, designations, RA/Dec, choosing between matches) | Working |
| MAST search: HST, JWST, Pan-STARRS | Working |
| Colour sets, filters, previews, selection | Working |
| ESO, IRSA, CADC | Not built yet (access verified for ESO and IRSA) |
| Download and science-image extraction, star-core repair, cut-outs, reprojection | Not built yet |

## Install

Needs Python 3.10 or newer.

```bash
git clone https://github.com/k822wfcgb8-web/FITS-fetcher.git
cd FITS-fetcher
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

## Run

```bash
.venv/bin/fits-fetcher
```

This starts a small server on your own computer (reachable only from it) and opens the search page in your
browser. Stop it with the page's **Quit** button or Ctrl+C in the terminal. Options: `--port N`, `--no-browser`.

Settings are stored in your platform's standard settings folder (on macOS,
`~/Library/Application Support/fits-fetcher/settings.json`), and a log file is written to the standard log folder.

## Tests

```bash
.venv/bin/python -m pytest              # offline tests
.venv/bin/python -m pytest -m network   # live checks against the archives
```

## Licence

GNU General Public License v3 or later (see REQUIREMENTS.md, REQ-34).
