"""In-memory job tracking and the bridge between blocking work and asyncio.

Downloads and ffmpeg runs happen in worker threads. Progress callbacks fire on
those threads and are marshalled onto the event loop with
``call_soon_threadsafe`` so the SSE endpoint can stream them. State lives in
memory, which is the right scope for a single-user localhost tool.
"""

from __future__ import annotations

import asyncio
import functools
import logging
import os
import re
import shutil
import tempfile
import threading
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from . import downloader, media
from .media import Emit
from .models import ExportRequest, JobStatus

log = logging.getLogger(__name__)

RETENTION = 3600  # seconds a finished job's files stay for re-saving or more exports
SWEEP_INTERVAL = 60

_ANSI = re.compile(r"\x1b\[[0-9;]*m")

Work = Callable[["Job", Emit], Awaitable[None]]


@dataclass
class Job:
    id: str
    url: str
    tmpdir: str
    status: JobStatus = JobStatus.running
    title: str = "video"
    filepath: str | None = None
    ext: str | None = None
    filesize: int | None = None
    error: str | None = None
    # Preview (source) jobs: the retained original plus a browser-playable proxy.
    previewpath: str | None = None
    probe: media.Probe | None = None
    users: int = 0  # exports currently reading this job's file
    # Export jobs: the preview job they cut from.
    source: Job | None = None
    finished_at: float | None = None
    queue: asyncio.Queue[dict[str, Any] | None] = field(default_factory=asyncio.Queue)
    done: asyncio.Event = field(default_factory=asyncio.Event)

    @property
    def duration(self) -> float | None:
        return self.probe.duration if self.probe else None

    def touch(self) -> None:
        """Restart the retention clock; called whenever the job's files are used."""
        self.finished_at = time.monotonic()

    @property
    def ready(self) -> bool:
        return self.status is JobStatus.completed and bool(self.filepath)

    def terminal_event(self) -> dict[str, Any]:
        if self.status is JobStatus.completed:
            return {
                "phase": "complete",
                "status": "completed",
                "title": self.title,
                "ext": self.ext,
                "filesize": self.filesize,
                "duration": self.duration,
                "lossless": media.lossless_containers(self.probe) if self.probe else [],
            }
        return {"phase": "complete", "status": "error", "error": self.error or "Something went wrong."}


class JobManager:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def create_preview(self, url: str) -> Job:
        """Fetch the original and an editing proxy for ``url``."""
        return self._start(url, self._prepare_preview)

    def create_export(self, source: Job, req: ExportRequest) -> Job:
        """Cut an export from a completed preview job's original file."""
        source.users += 1
        source.touch()
        return self._start(source.url, functools.partial(self._export, req=req), source=source)

    def sweep(self) -> None:
        """Drop finished jobs older than ``RETENTION`` that no export still reads."""
        now = time.monotonic()
        for job in list(self._jobs.values()):
            if not job.users and job.finished_at is not None and now - job.finished_at > RETENTION:
                self.remove(job)

    async def sweep_forever(self) -> None:
        while True:
            await asyncio.sleep(SWEEP_INTERVAL)
            self.sweep()

    def remove(self, job: Job) -> None:
        self._jobs.pop(job.id, None)
        shutil.rmtree(job.tmpdir, ignore_errors=True)

    def shutdown(self) -> None:
        for job in list(self._jobs.values()):
            self.remove(job)

    # ------------------------------------------------------------------ #
    def _start(self, url: str, work: Work, **fields: Any) -> Job:
        self.sweep()
        job = Job(id=uuid.uuid4().hex[:12], url=url, tmpdir=tempfile.mkdtemp(prefix="tubeworm-"), **fields)
        self._jobs[job.id] = job
        asyncio.create_task(self._run(job, work))
        return job

    async def _run(self, job: Job, work: Work) -> None:
        loop = asyncio.get_running_loop()
        loop_thread = threading.get_ident()

        def emit(event: dict[str, Any]) -> None:  # safe from any thread
            if threading.get_ident() == loop_thread:
                job.queue.put_nowait(event)
            else:
                loop.call_soon_threadsafe(job.queue.put_nowait, event)

        try:
            await work(job, emit)
            assert job.filepath
            job.filesize = os.path.getsize(job.filepath)
            job.status = JobStatus.completed
        except Exception as exc:  # noqa: BLE001 — every failure is surfaced to the UI
            log.warning("job %s failed: %s", job.id, exc)
            job.status = JobStatus.error
            job.error = friendly_error(exc)
        finally:
            if job.source is not None:
                job.source.users -= 1
                job.source.touch()
            job.touch()
            job.queue.put_nowait(job.terminal_event())
            job.queue.put_nowait(None)  # end of stream
            job.done.set()

    async def _prepare_preview(self, job: Job, emit: Emit) -> None:
        info = await asyncio.to_thread(downloader.fetch_info, job.url)
        if not info.duration or info.duration <= 0:
            raise ValueError("Only finished videos with a known length can be edited.")

        def proxy_emit(event: dict[str, Any]) -> None:
            status = "converting" if event.get("step") == "preview" else "downloading"
            if status != proxy_status[0]:
                proxy_status[0] = status
                emit({"phase": "proxy", "status": status})

        proxy_status = [None]
        source_task = asyncio.create_task(
            asyncio.to_thread(
                downloader.download,
                job.url,
                downloader.SOURCE_FORMAT,
                "mkv",
                os.path.join(job.tmpdir, "source"),
                emit,
            )
        )
        proxy_task = asyncio.create_task(
            asyncio.to_thread(
                downloader.download_proxy,
                job.url,
                os.path.join(job.tmpdir, "proxy"),
                proxy_emit,
            )
        )
        await asyncio.wait({source_task})
        if not proxy_task.done():
            emit({"phase": "process", "step": "preview-wait"})
        # Both threads must settle before we touch or delete anything.
        source, proxy = await asyncio.gather(source_task, proxy_task, return_exceptions=True)
        if isinstance(source, BaseException):
            raise source
        job.filepath, job.ext, job.title = source.filepath, source.ext, source.title
        job.probe = await asyncio.to_thread(media.probe, source.filepath)
        if isinstance(proxy, BaseException):
            log.warning("proxy download failed (%s); preparing the preview from the original", proxy)
            proxy = await asyncio.to_thread(media.prepare_preview, source.filepath, job.tmpdir, emit)
        job.previewpath = proxy
        emit({"phase": "proxy", "status": "ready"})

    async def _export(self, job: Job, emit: Emit, req: ExportRequest) -> None:
        source = job.source
        assert source is not None and source.filepath and source.probe
        job.filepath = await asyncio.to_thread(
            media.export_clip, source.filepath, source.probe, req, job.tmpdir, emit
        )
        job.ext = os.path.splitext(job.filepath)[1][1:]
        job.title = clip_title(source.title, req, source.probe.duration)


def clip_title(title: str, req: ExportRequest, duration: float) -> str:
    end = req.end_time if req.end_time is not None else duration
    whole = req.start_time <= media.WHOLE_TOLERANCE and end >= duration - media.WHOLE_TOLERANCE
    return title if whole else f"{title} [{_stamp(req.start_time)}-{_stamp(end)}]"


def _stamp(seconds: float) -> str:
    t = int(seconds)
    h, m, s = t // 3600, t % 3600 // 60, t % 60
    return f"{h}h{m:02d}m{s:02d}s" if h else f"{m}m{s:02d}s"


def friendly_error(exc: BaseException) -> str:
    """First line of an exception message, minus yt-dlp's colour codes and prefix."""
    msg = _ANSI.sub("", str(exc)).strip()
    msg = msg.splitlines()[0] if msg else ""
    if msg.lower().startswith("error:"):
        msg = msg[len("error:") :].strip()
    return msg or "Something went wrong."
