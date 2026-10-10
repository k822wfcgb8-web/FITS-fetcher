"""Filter names → central wavelength and broadband/narrowband type (REQ-19, S-17, S-21)."""
from __future__ import annotations

import re

# Named broadband filters (central wavelength in µm).
_NAMED = {
    "u": 0.355, "g": 0.48, "r": 0.62, "i": 0.75, "z": 0.87, "y": 0.96,   # SDSS / Pan-STARRS
    "J": 1.25, "H": 1.65, "K": 2.17, "Ks": 2.15,                          # 2MASS / VISTA
    "W1": 3.4, "W2": 4.6, "W3": 12.0, "W4": 22.0,                         # WISE
    "IRAC1": 3.6, "IRAC2": 4.5, "IRAC3": 5.8, "IRAC4": 8.0, "MIPS24": 24.0,  # Spitzer
}

# Emission lines offered as narrowband choices (REQ-19), rest wavelength in µm.
EMISSION_LINES = {
    "Hα": 0.6563, "Hβ": 0.4861, "[OIII]": 0.5007, "[SII]": 0.6724, "[NII]": 0.6584,
}

# HST/JWST style names: F + digits + W/M/N/LP (+ optional suffix).
_HST_JWST = re.compile(r"^F(\d{3,4})(W2|W|M|N|LP)\b", re.IGNORECASE)


# Instruments whose F-numbers are in units of 10 nm rather than 1 nm.
_TEN_NM_INSTRUMENTS = ("WFC3/IR", "NICMOS", "NIRCAM", "NIRISS", "MIRI")


def parse(filter_name: str, instrument: str = "") -> tuple[float | None, str]:
    """Return (central wavelength in µm or None, "broad" | "narrow").

    F-numbers depend on the instrument: HST UV/optical F435W is 0.435 µm, but HST IR (WFC3/IR, NICMOS)
    and JWST F160W/F200W are 1.60/2.00 µm. The name alone is ambiguous (WFPC2 F218W vs NICMOS F222M).
    """
    name = (filter_name or "").strip()
    if name in _NAMED:
        return _NAMED[name], "broad"
    m = _HST_JWST.match(name)
    if m:
        number, kind = int(m.group(1)), m.group(2).upper()
        ten_nm = any(instrument.upper().startswith(p) for p in _TEN_NM_INSTRUMENTS)
        wl = number / 100 if ten_nm else number / 1000
        return wl, "narrow" if kind == "N" else "broad"
    return None, "broad"


def line_for(wavelength_um: float | None, tolerance_um: float = 0.004) -> str | None:
    """Which emission line (if any) a narrowband filter isolates, for the REQ-19 line filter."""
    if wavelength_um is None:
        return None
    best = min(EMISSION_LINES.items(), key=lambda kv: abs(kv[1] - wavelength_um))
    return best[0] if abs(best[1] - wavelength_um) <= tolerance_um else None


def effective_filter(filter_name: str) -> str | None:
    """The single filter that defines the passband, or None for multi-filter / white-light products.

    'CLEAR1L;F435W' → 'F435W' (clear wheel position dropped); 'F444W;F405N' → 'F405N' (JWST NIRCam:
    a narrow/medium pupil filter inside a wide filter sets the band); 'detection' or 'F435W;F814W' → None
    (combined detection images, findings step 01). HAP products join parts with '-' instead of ';'.
    Polarizer images ('F606W-POL0V', 'F547M-POLQ') record one polarization angle and ramp filters ('FR…')
    change passband across the image, so neither is a colour channel → None.
    """
    parts = [p.strip() for p in re.split(r"[;-]", filter_name or "")]
    parts = [p for p in parts if p and not p.upper().startswith("CLEAR")]
    if any("POL" in p.upper() or p.upper().startswith("FR") for p in parts):
        return None
    if len(parts) == 1:
        name = parts[0]
        return None if name.lower() in {"detection", "none", "--", "opaque"} else name
    if len(parts) == 2:
        kinds = [(_HST_JWST.match(p).group(2).upper() if _HST_JWST.match(p) else "") for p in parts]
        wide = [p for p, k in zip(parts, kinds) if k in ("W", "W2", "LP")]
        narrow = [p for p, k in zip(parts, kinds) if k in ("N", "M")]
        if len(wide) == 1 and len(narrow) == 1:
            return narrow[0]
    return None
