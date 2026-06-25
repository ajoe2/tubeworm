"""FastAPI application: REST + SSE API and static frontend hosting."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from . import __version__, downloader
from .jobs import Job, JobManager
from .models import (
    CONTENT_TYPES,
    JobCreated,
    JobRequest,
    JobStatus,
    MediaInfo,
)

manager = JobManager()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    manager.shutdown()  # tidy up any leftover temp files on exit


app = FastAPI(title="tubeworm", version=__version__, lifespan=lifespan)

# Same-origin in production (the SPA is served from this app). Permissive for
# localhost dev where the Vite dev server runs on a different port.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class InfoRequest(BaseModel):
    url: str


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


@app.post("/api/info", response_model=MediaInfo)
async def info(req: InfoRequest) -> MediaInfo:
    url = req.url.strip()
    if not url:
        raise HTTPException(status_code=400, detail="A YouTube link is required.")
    try:
        return await asyncio.to_thread(downloader.fetch_info, url)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=_clean_error(exc)) from exc


@app.post("/api/jobs", response_model=JobCreated)
async def create_job(req: JobRequest) -> JobCreated:
    job = manager.create(req)
    return JobCreated(id=job.id)


@app.get("/api/jobs/{job_id}/events")
async def job_events(job_id: str) -> EventSourceResponse:
    job = manager.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown job.")

    async def stream():
        # If the job already finished before this stream connected, just emit a
        # terminal snapshot so the client isn't left waiting on an empty queue.
        if job.done.is_set():
            yield {"data": json.dumps(_terminal_snapshot(job))}
            return
        while True:
            event = await job.queue.get()
            if event is None:  # sentinel
                break
            yield {"data": json.dumps(event)}

    return EventSourceResponse(stream())


@app.get("/api/jobs/{job_id}/file")
async def job_file(job_id: str) -> FileResponse:
    job = manager.get(job_id)
    if job is None or job.status is not JobStatus.completed or not job.filepath:
        raise HTTPException(status_code=404, detail="File is not ready.")
    media_type = CONTENT_TYPES.get(job.ext or "", "application/octet-stream")
    # Not deleted on send: the file lingers until the next download is started
    # (see JobManager._sweep_finished) so the user can re-save if needed.
    return FileResponse(
        job.filepath,
        media_type=media_type,
        filename=_download_name(job),
    )


def _terminal_snapshot(job: Job) -> dict:
    if job.status is JobStatus.completed:
        return {
            "phase": "complete",
            "status": "completed",
            "title": job.title,
            "ext": job.ext,
            "filesize": job.filesize,
        }
    return {
        "phase": "complete",
        "status": "error",
        "error": job.error or "Download failed.",
    }


def _download_name(job: Job) -> str:
    title = (job.title or "download").strip()
    # Drop characters that are illegal in filenames / Content-Disposition.
    title = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", title).strip(". ") or "download"
    return f"{title}.{job.ext}"


def _clean_error(exc: Exception) -> str:
    msg = re.sub(r"\x1b\[[0-9;]*m", "", str(exc)).strip()
    if msg.lower().startswith("error:"):
        msg = msg[len("error:"):].strip()
    return (msg.splitlines()[0] if msg else "Could not read that link.") or "Could not read that link."


# --------------------------------------------------------------------------- #
# Static frontend (built by Vite into app/static). Mounted last so it never
# shadows the API routes above.
# --------------------------------------------------------------------------- #
_STATIC_DIR = Path(__file__).parent / "static"
if _STATIC_DIR.is_dir():
    app.mount("/", StaticFiles(directory=_STATIC_DIR, html=True), name="static")
else:

    @app.get("/", response_class=HTMLResponse)
    async def _dev_placeholder() -> str:
        return (
            "<main style='font-family:system-ui;max-width:40rem;margin:4rem auto;"
            "padding:0 1rem;color:#e8edef;background:#0b1014'>"
            "<h1>tubeworm</h1>"
            "<p>The API is running, but the frontend hasn't been built yet.</p>"
            "<p>For development run the Vite dev server in <code>frontend/</code> "
            "(<code>npm run dev</code>); for production build it so it lands in "
            "<code>app/static</code>.</p></main>"
        )
