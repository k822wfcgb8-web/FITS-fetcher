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
