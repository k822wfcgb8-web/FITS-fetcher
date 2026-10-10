"""Local web server (REQ-09): serves the search page and a small JSON / server-sent-events API.

Searches run each selected archive in a worker thread and stream results as each one answers (S-32).
An archive that fails or times out is reported without stopping the others (S-03, S-33). Closing the
page's event stream (Cancel) stops the stream; results still arriving from archives are discarded (S-07).
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import asdict, replace
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from fits_fetcher import __version__, filters
from fits_fetcher.archives import ARCHIVES, PLANNED, ArchiveError, Target
from fits_fetcher.config import Settings
from fits_fetcher.grouping import build_sets
from fits_fetcher.resolve import ResolveError, resolve

log = logging.getLogger(__name__)
STATIC = Path(__file__).parent / "static"

# Archive query cone. Results are then kept only if their footprint contains the object's centre (REQ-14),
# so the cone only needs to be big enough to catch every image that covers the centre.
QUERY_RADIUS_DEG = 0.02


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def create_app(settings: Settings | None = None, on_quit=None) -> FastAPI:
    settings = settings or Settings.load()
    app = FastAPI(title="FITS-fetcher", version=__version__)
    app.mount("/static", StaticFiles(directory=STATIC), name="static")

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
                    yield _sse("status", {"archive": name, "state": "done", "count": len(found)})
                    sets = build_sets(products, min_filters=min_filters, mix_instruments=mix_instruments,
                                      band_type=band_type, lines=line_set,
                                      pixel_scale_warn_ratio=settings.pixel_scale_warn_ratio)
                    yield _sse("sets", {"target": asdict(target), "sets": [s.to_dict() for s in sets],
                                        "products_found": len(products)})
            yield _sse("end", {})

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache"})

    @app.post("/api/quit")
    def quit_app():
        if on_quit:
            on_quit()
        return {"ok": True}

    return app
