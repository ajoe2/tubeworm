"""In-memory job tracking and the bridge between blocking yt-dlp and asyncio.

A download runs in a worker thread (yt-dlp is blocking). Its progress hook fires
on that thread; we marshal each event onto the event loop's queue with
``call_soon_threadsafe`` so the SSE endpoint can stream it. State is kept in
memory, which is the right scope for a single-user localhost tool.
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from . import downloader
from .models import JobRequest, JobStatus

_ANSI = re.compile(r"\x1b\[[0-9;]*m")


@dataclass
class Job:
    id: str
    request: JobRequest
    status: JobStatus = JobStatus.pending
    preview: bool = False
    previewpath: str | None = None
    duration: float | None = None
    source: Job | None = None
    users: int = 0
    title: str | None = None
    filepath: str | None = None
    ext: str | None = None
    filesize: int | None = None
    error: str | None = None
    tmpdir: str | None = None
    created: float = field(default_factory=time.monotonic)
    finished_at: float | None = None
    queue: asyncio.Queue[dict[str, Any] | None] = field(default_factory=asyncio.Queue)
    done: asyncio.Event = field(default_factory=asyncio.Event)


class JobManager:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def create(self, request: JobRequest, *, preview: bool = False, source: Job | None = None) -> Job:
        # Retain recent results so concurrent tabs can finish saving their files.
        if source is not None:
            source.users += 1
            source.finished_at = time.monotonic()
        self._sweep_finished()
        job = Job(id=uuid.uuid4().hex[:12], request=request, preview=preview, source=source)
        self._jobs[job.id] = job
        loop = asyncio.get_running_loop()
        asyncio.create_task(self._run(job, loop))
        return job

    def cleanup(self, job: Job) -> None:
        """Drop the job and remove its temp directory."""
        self._jobs.pop(job.id, None)
        if job.tmpdir and os.path.isdir(job.tmpdir):
            shutil.rmtree(job.tmpdir, ignore_errors=True)

    def _sweep_finished(self) -> None:
        """Expire results one hour after completion; leave in-flight jobs alone."""
        for job in list(self._jobs.values()):
            if not job.users and job.finished_at is not None and time.monotonic() - job.finished_at > 3600:
                self.cleanup(job)

    def shutdown(self) -> None:
        """Remove every temp directory; called on application shutdown."""
        for job in list(self._jobs.values()):
            self.cleanup(job)

    async def _run(self, job: Job, loop: asyncio.AbstractEventLoop) -> None:
        job.tmpdir = tempfile.mkdtemp(prefix="tubeworm-")

        def publish(event: dict[str, Any]) -> None:
            self._apply_status(job, event)
            job.queue.put_nowait(event)

        def emit(event: dict[str, Any]) -> None:
            loop.call_soon_threadsafe(publish, event)

        try:
            if job.source is not None:
                result = await asyncio.to_thread(downloader.export_selection, job.request,
                    job.source.filepath, job.source.duration, job.tmpdir, emit)
                result["title"] = f"{job.source.title or 'Video'} - clip"
            elif job.preview:
                info = await asyncio.to_thread(downloader.fetch_info, job.request.url)
                if not info.duration or info.duration <= 0:
                    raise ValueError("The editor requires a finished video with a known duration.")
                # A lightweight proxy can be fetched and prepared while the larger
                # original downloads. Both workers settle before cleanup or fallback.
                original_done = asyncio.Event()
                last_proxy_status = None
                def proxy_emit(event: dict[str, Any]) -> None:
                    nonlocal last_proxy_status
                    signature = (event.get("phase"), event.get("status"), event.get("postprocessor"))
                    if signature == last_proxy_status:
                        return
                    last_proxy_status = signature
                    # Original progress drives the main meter. Keep preview status
                    # separate so concurrent processing cannot replace download state.
                    loop.call_soon_threadsafe(job.queue.put_nowait, {
                        "phase": "preview", "status": event.get("status"),
                        "postprocessor": event.get("postprocessor"),
                    })
                async def original():
                    try:
                        return await asyncio.to_thread(downloader.run_download, job.request, job.tmpdir, emit)
                    finally:
                        original_done.set()
                async def proxy():
                    result = await asyncio.to_thread(downloader.download_preview, job.request.url, job.tmpdir, proxy_emit)
                    await job.queue.put({"phase": "preview", "status": "completed"})
                    return result
                original_task = asyncio.create_task(original())
                proxy_task = asyncio.create_task(proxy())
                await original_done.wait()
                if not proxy_task.done():
                    emit({"phase": "postprocess", "status": "started", "postprocessor": "PreviewWait"})
                results = await asyncio.gather(original_task, proxy_task, return_exceptions=True)
                if isinstance(results[0], BaseException):
                    raise results[0]
                result = results[0]
                if isinstance(results[1], BaseException):
                    # If the extra preview request is unavailable, retain a usable
                    # editor by preparing the successfully downloaded original.
                    job.previewpath, job.duration = await asyncio.to_thread(
                        downloader.prepare_preview, result["filepath"], job.tmpdir, emit)
                else:
                    job.previewpath, job.duration = results[1]
            else:
                result = await asyncio.to_thread(downloader.run_download, job.request, job.tmpdir, emit)

            job.filepath = result["filepath"]
            job.title = result["title"]
            job.ext = result["ext"]
            job.filesize = os.path.getsize(job.filepath)
            job.status = JobStatus.completed
            await job.queue.put(
                {
                    "phase": "complete",
                    "status": "completed",
                    "title": job.title,
                    "ext": job.ext,
                    "filesize": job.filesize,
                    "duration": job.duration,
                }
            )
        except Exception as exc:  # noqa: BLE001 — surface any failure to the UI
            job.status = JobStatus.error
            job.error = _friendly_error(exc)
            await job.queue.put(
                {"phase": "complete", "status": "error", "error": job.error}
            )
        finally:
            if job.source is not None:
                job.source.users -= 1
                job.source.finished_at = time.monotonic()
            await job.queue.put(None)  # sentinel: end of stream
            job.finished_at = time.monotonic()
            job.done.set()

    @staticmethod
    def _apply_status(job: Job, event: dict[str, Any]) -> None:
        phase = event.get("phase")
        if phase == "download" and event.get("status") == "downloading":
            job.status = JobStatus.downloading
        elif phase == "postprocess":
            job.status = JobStatus.processing


def _friendly_error(exc: Exception) -> str:
    msg = _ANSI.sub("", str(exc)).strip()
    if msg.lower().startswith("error:"):
        msg = msg[len("error:"):].strip()
    msg = msg.splitlines()[0] if msg else "Download failed."
    return msg or "Download failed."
