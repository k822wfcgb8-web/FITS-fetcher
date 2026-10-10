"""User settings (S-08, S-34), stored as JSON in the platform's standard config folder."""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

from platformdirs import user_cache_dir, user_config_dir, user_log_dir

APP = "fits-fetcher"
log = logging.getLogger(__name__)


def config_path() -> Path:
    return Path(user_config_dir(APP)) / "settings.json"


def log_path() -> Path:
    return Path(user_log_dir(APP)) / "fits-fetcher.log"


@dataclass
class Settings:
    output_dir: str = str(Path.home() / "FITS-fetcher")
    cache_dir: str = user_cache_dir(APP)
    size_warning_gb: float = 5.0             # S-26
    parallel_downloads: int = 3              # S-28, per archive
    archive_timeout_s: int = 60              # S-32
    min_filters: int = 3                     # REQ-10
    mix_instruments: bool = False            # REQ-11
    pixel_scale_warn_ratio: float = 4.0      # REQ-26
    star_repair: bool = True                 # REQ-42
    star_repair_max_area: int = 2000         # REQ-38
    reproject: bool = False                  # REQ-24
    cutout: bool = False                     # REQ-25
    cutout_default_arcmin: float = 10.0      # REQ-25/REQ-58 box when the object's size is unknown
    hst_show_mosaics: bool = False           # REQ-58
    # Collection allow-lists live in configuration, not code (REQ-35, REQ-55, REQ-56).
    mast_collections: list[str] = field(default_factory=lambda: ["HST", "JWST", "PS1"])
    irsa_collections: list[str] = field(default_factory=lambda: ["spitzer_seip", "wise_allwise", "twomass_allsky"])
    cadc_excluded_collections: list[str] = field(default_factory=lambda: ["HST", "HSTHLA", "JWST"])

    @classmethod
    def load(cls, path: Path | None = None) -> Settings:
        path = path or config_path()
        try:
            raw = json.loads(path.read_text())
        except FileNotFoundError:
            return cls()
        except (OSError, json.JSONDecodeError) as e:
            log.warning("Could not read settings from %s (%s); using defaults", path, e)
            return cls()
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in raw.items() if k in known})

    def save(self, path: Path | None = None) -> None:
        path = path or config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2))


# Settings the settings dialog can change (REQ-64), with their allowed ranges. Collection lists stay file-only.
FOLDERS = ("output_dir", "cache_dir")
NUMBERS: dict[str, tuple[type, float, float, str]] = {
    "size_warning_gb": (float, 0.1, 10_000, "GB"),
    "parallel_downloads": (int, 1, 10, "downloads"),
    "archive_timeout_s": (int, 10, 600, "seconds"),
    "min_filters": (int, 2, 20, "filters"),
    "pixel_scale_warn_ratio": (float, 1, 1000, "×"),
    "star_repair_max_area": (int, 1, 1_000_000, "pixels"),
    "cutout_default_arcmin": (float, 0.1, 600, "arcmin"),
}
SWITCHES = ("mix_instruments", "hst_show_mosaics", "star_repair", "cutout")
EDITABLE = FOLDERS + tuple(NUMBERS) + SWITCHES


def check_folder(path: str) -> tuple[str, str | None]:
    """REQ-65: (expanded path, error). The folder must exist or be creatable, and be writable."""
    if not path.strip():
        return path, "Enter a folder."
    p = Path(path.strip()).expanduser()
    if not p.is_absolute():
        return str(p), "Use a full path, e.g. starting with / or ~."
    try:
        p.mkdir(parents=True, exist_ok=True)
        probe = p / ".fits-fetcher-write-test"
        probe.write_text("")
        probe.unlink()
    except OSError as e:
        return str(p), f"Can't use this folder: {e.strerror or e}."
    return str(p), None


def validated(current: Settings, changes: dict) -> tuple[Settings, dict[str, str]]:
    """Apply editable `changes` to a copy of `current`; returns (new settings, errors by field)."""
    values, errors = asdict(current), {}
    for key in FOLDERS:
        if key in changes:
            values[key], err = check_folder(str(changes[key]))
            if err:
                errors[key] = err
    for key, (kind, lo, hi, unit) in NUMBERS.items():
        if key not in changes:
            continue
        try:
            v = kind(changes[key])
            if kind is int and float(changes[key]) != v:
                raise ValueError
        except (TypeError, ValueError):
            errors[key] = "Enter a whole number." if kind is int else "Enter a number."
            continue
        if not lo <= v <= hi:
            errors[key] = f"Must be between {lo:g} and {hi:g} {unit}."
        values[key] = v
    for key in SWITCHES:
        if key in changes:
            values[key] = bool(changes[key])
    return Settings(**values), errors
