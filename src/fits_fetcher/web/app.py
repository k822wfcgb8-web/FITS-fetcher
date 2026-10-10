"""Local web server (REQ-09): serves the search page and a small JSON / server-sent-events API.

Searches run each selected archive in a worker thread and stream results as each one answers (S-32).
An archive that fails or times out is reported without stopping the others (S-03, S-33). Closing the
page's event stream (Cancel) stops the stream; results still arriving from archives are discarded (S-07).

Downloads (REQ-61–63) are started with the keys of products a search returned; the page never sends URLs,
so the server only fetches files it found itself. Progress streams as server-sent events.
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import asdict, replace
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from fits_fetcher import __version__, filters, footprint
from fits_fetcher.archives import ARCHIVES, PLANNED, ArchiveError, Product, Target
from fits_fetcher.config import Settings
from fits_fetcher.downloads import DownloadManager, Item, open_folder
from fits_fetcher.grouping import build_sets
from fits_fetcher.output import thumbnail_png
from fits_fetcher.processing import Options
from fits_fetcher.resolve import ResolveError, resolve

log = logging.getLogger(__name__)
STATIC = Path(__file__).parent / "static"

# Archive query cone. Results are then kept only if their footprint contains the object's centre (REQ-14),
# so the cone only needs to be big enough to catch every image that covers the centre.
QUERY_RADIUS_DEG = 0.02


PROGRESS_INTERVAL_S = 0.3


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


class DownloadItem(BaseModel):
    key: str
    sets: list[str] = []


class DownloadRequest(BaseModel):
    target: dict
    items: list[DownloadItem]
    star_repair: bool
    cutout: bool


def create_app(settings: Settings | None = None, on_quit=None) -> FastAPI:
    settings = settings or Settings.load()
    app = FastAPI(title="FITS-fetcher", version=__version__)
    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    known: dict[str, Product] = {}  # every product a search has returned, by key
    manager = DownloadManager(settings, ARCHIVES)

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    @app.get("/api/info")
    def info():
        return {"version": __version__, "archives": list(ARCHIVES), "planned": PLANNED,
                "emission_lines": list(filters.EMISSION_LINES), "settings": asdict(settings)}

    @app.get("/api/resolve")
    def resolve_name(q: str):
        try:
            targets = resolve(q)
        except ResolveError as e:
            raise HTTPException(404, str(e)) from e
        return {"targets": [asdict(t) for t in targets]}

    @app.get("/api/search")
    async def search(
        ra: float, dec: float, matched_id: str = "", query: str = "", size_arcmin: float | None = None,
        archives: str = "MAST", min_filters: int = Query(settings.min_filters, ge=2),
        mix_instruments: bool = settings.mix_instruments, band_type: str = "either", lines: str = "",
        hst_mosaics: bool = settings.hst_show_mosaics,
    ):
        target = Target(query=query, matched_id=matched_id, ra=ra, dec=dec, size_arcmin=size_arcmin)
        run_settings = replace(settings, hst_show_mosaics=hst_mosaics)
        chosen = [a for a in archives.split(",") if a in ARCHIVES]
        line_set = {line for line in lines.split(",") if line}

        async def stream():
            loop = asyncio.get_running_loop()
            pending = {}
            for name in chosen:
                archive = ARCHIVES[name](run_settings)
                fut = loop.run_in_executor(None, archive.search, target, QUERY_RADIUS_DEG)
                pending[asyncio.ensure_future(asyncio.wait_for(fut, settings.archive_timeout_s))] = name
                yield _sse("status", {"archive": name, "state": "searching"})
            products = []
            while pending:
                done, _ = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    name = pending.pop(task)
                    try:
                        found = task.result()
                    except asyncio.TimeoutError:
                        log.warning("%s timed out after %ss", name, settings.archive_timeout_s)
                        yield _sse("status", {"archive": name, "state": "timeout",
                                              "message": f"{name} didn't answer within {settings.archive_timeout_s} s."})
                        continue
                    except ArchiveError as e:
                        log.warning("%s failed: %s", name, e)
                        yield _sse("status", {"archive": name, "state": "failed",
                                              "message": f"{name} couldn't be searched: {e}"})
                        continue
                    except Exception as e:  # unexpected: log with traceback, tell the user plainly
                        log.exception("%s search crashed", name)
                        yield _sse("status", {"archive": name, "state": "failed",
                                              "message": f"{name} search failed unexpectedly ({type(e).__name__}). See the log file."})
                        continue
                    products.extend(found)
                    known.update((p.key, p) for p in found)
                    yield _sse("status", {"archive": name, "state": "done", "count": len(found)})
                    sets = build_sets(products, min_filters=min_filters, mix_instruments=mix_instruments,
                                      band_type=band_type, lines=line_set,
                                      pixel_scale_warn_ratio=settings.pixel_scale_warn_ratio)
                    yield _sse("sets", {"target": asdict(target), "sets": [s.to_dict() for s in sets],
                                        "products_found": len(products)})
            yield _sse("end", {})

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache"})

    @app.post("/api/download")
    def start_download(req: DownloadRequest):
        fields = {f for f in Target.__dataclass_fields__}
        target = Target(**{k: v for k, v in req.target.items() if k in fields})
        missing = [i.key for i in req.items if i.key not in known]
        if missing or not req.items:
            raise HTTPException(400, "Some selected images are no longer known to the server. Search again.")
        options = Options(star_repair=req.star_repair, repair_max_area=settings.star_repair_max_area,
                          cutout=req.cutout,
                          box_arcmin=footprint.box_arcmin(target.size_arcmin, settings.cutout_default_arcmin))
        job = manager.start(target, [Item(known[i.key], i.sets) for i in req.items], options)
        return job.snapshot()

    def _job(job_id: str):
        job = manager.get(job_id)
        if job is None:
            raise HTTPException(404, "No such download.")
        return job

    @app.get("/api/download/{job_id}/events")
    async def download_events(job_id: str):
        job = _job(job_id)

        async def stream():
            seen = -1
            while True:
                snap = job.snapshot()
                if snap["version"] != seen:
                    seen = snap["version"]
                    yield _sse("progress", snap)
                if snap["finished"]:
                    yield _sse("end", snap)
                    return
                await asyncio.sleep(PROGRESS_INTERVAL_S)

        return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})

    @app.post("/api/download/{job_id}/cancel")
    def cancel_download(job_id: str):
        _job(job_id).cancel()
        return {"ok": True}

    @app.post("/api/download/{job_id}/open")
    def open_download_folder(job_id: str):
        folder = _job(job_id).object_dir
        if not folder.is_dir():
            raise HTTPException(404, "The folder doesn't exist yet: nothing was saved.")
        open_folder(folder)
        return {"ok": True}

    @app.get("/api/download/{job_id}/thumb")
    def download_thumbnail(job_id: str, key: str):
        item = next((it for it in _job(job_id).items if it.product.key == key), None)
        if item is None or not item.paths:
            raise HTTPException(404, "Not downloaded.")
        try:
            png = thumbnail_png(Path(item.paths[0]))
        except (OSError, ValueError) as e:
            raise HTTPException(500, f"Couldn't make a thumbnail: {e}") from e
        return Response(png, media_type="image/png")

    @app.post("/api/quit")
    def quit_app():
        if on_quit:
            on_quit()
        return {"ok": True}

    return app
