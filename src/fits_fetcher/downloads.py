"""Download jobs: fetch, process and save the selected products (Section 8, REQ-61–63).

- Up to `parallel_downloads` downloads run at once per archive (S-28).
- Processing runs one image at a time: an HST mosaic strip can be gigabytes in memory.
- An output that already exists with the same settings is skipped (S-27, REQ-54). A product in several colour
  sets is processed once and copied into each set folder (S-29).
- Cache files are deleted once the output is saved; if processing fails they are kept and the error logged (REQ-23).
- Cancel stops downloads between chunks; partial files stay in the cache so a later download resumes (S-07, S-27).
- With 'Save a data mask' on, each image gets `<name>_mask.fits` beside it, and images on one grid a combined
  `Grid_<grid>_mask.fits` in each set folder (REQ-101–REQ-103).
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import threading
import time
import uuid
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from pathlib import Path

from astropy.io import fits

from fits_fetcher.archives.base import Archive, ArchiveError, Product, Target
from fits_fetcher.config import Settings
from fits_fetcher.masks import combine_grid, mask_path, write_mask
from fits_fetcher.output import object_folder, output_paths, write_credits
from fits_fetcher.processing import Options, ProcessingError, existing_matches, grid_id, process, save
from fits_fetcher.transfer import Cancelled, Transfer, TransferError

log = logging.getLogger(__name__)
FINAL = ("saved", "skipped", "failed", "cancelled")
KEEP_JOBS = 20


@dataclass
class Item:
    product: Product
    sets: list[str]
    state: str = "queued"     # queued → downloading → processing → saved | skipped | failed | cancelled
    done: int = 0             # bytes downloaded
    total: int = 0            # bytes to download (estimate until the download starts)
    message: str = ""
    paths: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"key": self.product.key, "state": self.state, "done": self.done, "total": self.total,
                "message": self.message, "paths": self.paths}


class DownloadJob:
    def __init__(self, target: Target, items: list[Item], options: Options, settings: Settings,
                 archives: dict[str, type[Archive]]):
        self.id = uuid.uuid4().hex[:12]
        self.target, self.items, self.options, self.settings = target, items, options, settings
        self.archives = archives
        self.cancel_event = threading.Event()
        self.transfer = Transfer(settings.cache_dir, self.cancel_event)
        self.object_dir = Path(settings.output_dir).expanduser() / object_folder(target)
        self.finished = False
        self.version = 0
        self._lock = threading.Lock()
        self._processing = threading.Semaphore(1)
        self._grid_boxes: dict[str, str] = {}  # REQ-75: grid ID → trim box (FFTRIMBX) its first image used
        self._grid_names = {grid_id(it.product): it.product.grid for it in items if it.product.grid}  # REQ-103
        self._pools: list[ThreadPoolExecutor] = []
        for it in items:
            it.total = it.product.size_bytes or 0

    # ---------- control ----------
    def start(self) -> None:
        by_archive: dict[str, list[Item]] = defaultdict(list)
        for it in self.items:
            by_archive[it.product.archive].append(it)
        futures = []
        for name, items in by_archive.items():
            pool = ThreadPoolExecutor(max_workers=max(1, self.settings.parallel_downloads), thread_name_prefix=f"dl-{name}")
            self._pools.append(pool)
            archive = self.archives[name](self.settings) if name in self.archives else None
            futures += [pool.submit(self._run, it, archive) for it in items]
        threading.Thread(target=self._finish, args=(futures,), daemon=True, name=f"job-{self.id}").start()

    def cancel(self) -> None:
        self.cancel_event.set()
        for pool in self._pools:
            pool.shutdown(wait=False, cancel_futures=True)

    def _finish(self, futures) -> None:
        # Poll done() rather than wait(): wait() never counts a future cancelled while still queued (Cancel).
        while not all(f.done() for f in futures):
            time.sleep(0.2)
        for it in self.items:
            if it.state not in FINAL:  # never started because Cancel was pressed
                self._update(it, state="cancelled", message="Cancelled.")
        if any(it.state in ("saved", "skipped") for it in self.items):
            try:
                write_credits(self.object_dir)
            except OSError as e:
                log.warning("Could not write the credits file in %s: %s", self.object_dir, e)
        with self._lock:
            self.finished = True
            self.version += 1

    # ---------- one product ----------
    def _update(self, item: Item, **changes) -> None:
        with self._lock:
            for k, v in changes.items():
                setattr(item, k, v)
            self.version += 1

    def _run(self, item: Item, archive: Archive | None) -> None:
        try:
            self.transfer.check()
            self._download(item, archive)
        except Cancelled:
            self._update(item, state="cancelled", message="Cancelled.")
        except (ArchiveError, TransferError, ProcessingError) as e:
            log.warning("%s failed: %s", item.product.key, e)
            self._update(item, state="failed", message=str(e))
        except Exception as e:  # unexpected: log with traceback, tell the user plainly
            log.exception("%s failed unexpectedly", item.product.key)
            self._update(item, state="failed", message=f"Unexpected error ({type(e).__name__}: {e}). See the log file.")

    def _download(self, item: Item, archive: Archive | None) -> None:
        p = item.product
        options = self.options.for_product(p)
        paths = output_paths(self.settings.output_dir, self.target, p, item.sets)
        existing = next((x for x in paths if x.exists() and existing_matches(x, options)), None)
        if existing:
            for x in paths:
                if x != existing and not (x.exists() and existing_matches(x, options)):
                    self._copy(existing, x, options)
            if options.data_mask:
                self._grid_masks(paths, existing)
            self._update(item, state="skipped", done=item.total, paths=[str(x) for x in paths],
                         message="Already downloaded with these settings.")
            return
        if archive is None:
            raise ArchiveError(f"Downloading from {p.archive} isn't built yet.")

        self._update(item, state="downloading")
        fetched = archive.fetch(p, self.target, self.transfer, self.options.box_arcmin,
                                lambda done, total: self._update(item, done=done, total=total))
        self._update(item, state="processing", message="Waiting for the previous image to finish processing…")
        with self._processing:
            self.transfer.check()
            self._update(item, message="")
            box = self._grid_box(p) if p.grid else None
            result = process(fetched, p, self.target, options, grid_box=box)
            save(result, paths[0])
            if "FFTRIMBX" in result.header:
                self._grid_boxes.setdefault(result.header["FFGRID"], result.header["FFTRIMBX"])
            notes = " ".join(result.warnings)
            if result.mask is not None:
                gaps = write_mask(mask_path(paths[0]), result.mask, result.header, paths[0].name, [])
                if gaps:
                    notes = (notes + f" The data mask marks {gaps:,} pixels of gaps inside the field.").strip()
            del result
            for x in paths[1:]:
                self._copy(paths[0], x, options)
            if options.data_mask:
                self._grid_masks(paths, paths[0])
        for f in fetched.files:  # REQ-23: originals go once the output is safely saved
            f.unlink(missing_ok=True)
        self._update(item, state="saved", done=item.total, paths=[str(x) for x in paths], message=notes)

    @staticmethod
    def _copy(src: Path, dst: Path, options: Options) -> None:
        """S-29: a product in several sets is copied into each set folder, with its data mask (REQ-101)."""
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        if options.data_mask and mask_path(src).exists():
            shutil.copy2(mask_path(src), mask_path(dst))

    def _grid_masks(self, paths: list[Path], saved: Path) -> None:
        """REQ-103: refresh the combined mask of the saved image's grid in each of its set folders."""
        try:
            h = fits.getheader(mask_path(saved))
        except (OSError, ValueError):
            return
        grid, name = h.get("FFGRID"), self._grid_names.get(h.get("FFGRID", ""))
        if not grid or not name:
            return
        for x in paths:
            try:
                combine_grid(x.parent, grid, name)
            except (OSError, ValueError) as e:
                log.warning("Could not write the grid mask in %s: %s", x.parent, e)

    def _grid_box(self, p: Product) -> str | None:
        """REQ-75: the trim box of an image on `p`'s grid saved earlier, in this download or in the object's folder."""
        key = grid_id(p)
        if key not in self._grid_boxes:
            for path in sorted(self.object_dir.glob("*/*.fits")) if self.object_dir.is_dir() else []:
                try:
                    h = fits.getheader(path)
                except (OSError, ValueError):
                    continue
                if h.get("FFGRID") == key and h.get("FFTRIMBX"):
                    self._grid_boxes[key] = h["FFTRIMBX"]
                    break
        return self._grid_boxes.get(key)

    # ---------- reporting ----------
    def snapshot(self) -> dict:
        with self._lock:
            items = [it.to_dict() for it in self.items]
            counts = {s: sum(1 for it in self.items if it.state == s) for s in FINAL}
            total = sum(it.total for it in self.items)
            done = sum(it.total if it.state in ("saved", "skipped") else it.done for it in self.items)
            return {"id": self.id, "version": self.version, "finished": self.finished,
                    "cancelled": self.cancel_event.is_set(), "object_dir": str(self.object_dir),
                    "counts": counts, "bytes_done": done, "bytes_total": total, "items": items}


class DownloadManager:
    def __init__(self, settings: Settings, archives: dict[str, type[Archive]]):
        self.settings, self.archives = settings, archives
        self.jobs: dict[str, DownloadJob] = {}

    def start(self, target: Target, items: list[Item], options: Options) -> DownloadJob:
        # A copy: settings saved while this job runs don't change where it saves (REQ-66).
        job = DownloadJob(target, items, options, replace(self.settings), self.archives)
        self.jobs[job.id] = job
        for old in list(self.jobs)[:-KEEP_JOBS]:
            if self.jobs[old].finished:
                del self.jobs[old]
        job.start()
        return job

    def get(self, job_id: str) -> DownloadJob | None:
        return self.jobs.get(job_id)


def open_folder(path: Path) -> None:
    """REQ-63: show a folder in Finder / Explorer / the desktop's file manager."""
    if sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    elif sys.platform == "win32":
        os.startfile(str(path))  # noqa: S606 - local folder chosen by the app, not the page
    else:
        subprocess.Popen(["xdg-open", str(path)])
