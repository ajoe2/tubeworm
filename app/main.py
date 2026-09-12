"""FastAPI application: REST + SSE API and static frontend hosting."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from sse_starlette.sse import EventSourceResponse

from . import __version__, downloader
from .jobs import Job, JobManager, friendly_error
from .models import CONTENT_TYPES, ExportRequest, JobCreated, MediaInfo, PreviewRequest

manager = JobManager()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    sweeper = asyncio.create_task(manager.sweep_forever())
    try:
        yield
    finally:
        sweeper.cancel()
        manager.shutdown()  # remove every temp file on exit


app = FastAPI(title="tubeworm", version=__version__, lifespan=lifespan)


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


@app.post("/api/info", response_model=MediaInfo)
async def info(req: PreviewRequest) -> MediaInfo:
    """Title, channel, length and thumbnail; the extraction is reused by the load."""
    try:
        return await asyncio.to_thread(downloader.fetch_info, req.url)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=friendly_error(exc)) from exc


@app.post("/api/previews", response_model=JobCreated)
async def create_preview(req: PreviewRequest) -> JobCreated:
    return JobCreated(id=manager.create_preview(req.url).id)


@app.get("/api/previews/{job_id}/media")
async def preview_media(job_id: str) -> FileResponse:
    job = _preview(job_id)
    # Inline and range-capable so the <video> element can seek.
    return FileResponse(job.previewpath, media_type="video/mp4", content_disposition_type="inline")


@app.post("/api/previews/{job_id}/exports", response_model=JobCreated)
async def create_export(job_id: str, req: ExportRequest) -> JobCreated:
    source = _preview(job_id)
    duration = source.duration or 0
    if req.start_time >= duration or (req.end_time is not None and req.end_time > duration):
        raise HTTPException(status_code=422, detail="The selection is outside the video.")
    return JobCreated(id=manager.create_export(source, req).id)


@app.get("/api/jobs/{job_id}/events")
async def job_events(job_id: str) -> EventSourceResponse:
    job = manager.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown job.")

    async def stream():
        if job.done.is_set():  # finished before we connected: send the outcome only
            yield {"data": json.dumps(job.terminal_event())}
            return
        while (event := await job.queue.get()) is not None:
            yield {"data": json.dumps(event)}

    return EventSourceResponse(stream())


@app.get("/api/jobs/{job_id}/file")
async def job_file(job_id: str) -> FileResponse:
    job = manager.get(job_id)
    if job is None or not job.ready:
        raise HTTPException(status_code=404, detail="File is not ready.")
    return FileResponse(
        job.filepath,
        media_type=CONTENT_TYPES.get(job.ext or "", "application/octet-stream"),
        filename=_download_name(job),
    )


def _preview(job_id: str) -> Job:
    job = manager.get(job_id)
    if job is None or not job.ready or not job.previewpath or not job.duration:
        raise HTTPException(status_code=404, detail="That video has expired. Load it again.")
    job.touch()  # keep it alive while in use
    return job


def _download_name(job: Job) -> str:
    # Drop characters that are illegal in filenames / Content-Disposition.
    title = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", job.title).strip(". ") or "download"
    return f"{title}.{job.ext}"


# Static frontend (built by Vite into app/static). Mounted last so it never
# shadows the API routes above.
_STATIC_DIR = Path(__file__).parent / "static"
if _STATIC_DIR.is_dir():
    app.mount("/", StaticFiles(directory=_STATIC_DIR, html=True), name="static")
else:

    @app.get("/", response_class=HTMLResponse)
    async def _dev_placeholder() -> str:
        return (
            "<main style='font-family:system-ui;max-width:40rem;margin:4rem auto;padding:0 1rem'>"
            "<h1>tubeworm</h1><p>The API is running but the frontend is not built. "
            "Run <code>npm run dev</code> in <code>frontend/</code> for development, "
            "or <code>npm run build</code> to serve it from here.</p></main>"
        )
