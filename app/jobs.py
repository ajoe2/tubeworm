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
    title: str | None = None
    filepath: str | None = None
    ext: str | None = None
    filesize: int | None = None
    error: str | None = None
    tmpdir: str | None = None
    created: float = field(default_factory=time.monotonic)
    queue: asyncio.Queue[dict[str, Any] | None] = field(default_factory=asyncio.Queue)
    done: asyncio.Event = field(default_factory=asyncio.Event)


class JobManager:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def create(self, request: JobRequest) -> Job:
        # Starting a new download is the natural moment to discard the previous
        # finished file — we stream to the browser and keep nothing long-term.
        self._sweep_finished()
        job = Job(id=uuid.uuid4().hex[:12], request=request)
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
        """Remove temp dirs of jobs that have already finished (kept only so the
        user could re-trigger the browser save). In-flight jobs are left alone."""
        for job in list(self._jobs.values()):
            if job.done.is_set():
                self.cleanup(job)

    def shutdown(self) -> None:
        """Remove every temp directory; called on application shutdown."""
        for job in list(self._jobs.values()):
            self.cleanup(job)

    async def _run(self, job: Job, loop: asyncio.AbstractEventLoop) -> None:
        job.tmpdir = tempfile.mkdtemp(prefix="tubeworm-")

        def emit(event: dict[str, Any]) -> None:
            # Runs on the worker thread.
            self._apply_status(job, event)
            loop.call_soon_threadsafe(job.queue.put_nowait, event)

        try:
            result = await loop.run_in_executor(
                None, downloader.run_download, job.request, job.tmpdir, emit
            )
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
                }
            )
        except Exception as exc:  # noqa: BLE001 — surface any failure to the UI
            job.status = JobStatus.error
            job.error = _friendly_error(exc)
            await job.queue.put(
                {"phase": "complete", "status": "error", "error": job.error}
            )
        finally:
            await job.queue.put(None)  # sentinel: end of stream
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
