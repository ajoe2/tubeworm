"""yt-dlp integration: metadata lookup and parallel stream downloads.

Blocking and framework-agnostic. ``jobs.py`` runs these in worker threads and
forwards the normalized ``emit`` events to the browser.
"""

from __future__ import annotations

import copy
import os
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

from . import media
from .media import Emit
from .models import MediaInfo

# Best available streams (usually AV1/VP9 + Opus). Muxed losslessly into Matroska.
SOURCE_FORMAT = "bestvideo+bestaudio/best"
# A small H.264/AAC proxy the browser can play natively, or anything <=720p as a
# fallback that ``media.prepare_preview`` converts.
PROXY_FORMAT = (
    "bestvideo[vcodec^=avc1][height<=720]+bestaudio[ext=m4a]/"
    "best[vcodec^=avc1][height<=720]/"
    "bestvideo[height<=720]+bestaudio/best[height<=720]/best"
)

_INFO_TTL = 300  # seconds an extraction stays reusable
_INFO_CACHE_SIZE = 32
_PROGRESS_INTERVAL = 0.1  # seconds between progress events per download


@dataclass(frozen=True)
class Downloaded:
    filepath: str
    title: str
    ext: str


def fetch_info(url: str) -> MediaInfo:
    """Resolve metadata; the extraction is cached for the download that follows."""
    info = _source_info(url)
    return MediaInfo(
        title=info.get("title"),
        uploader=info.get("uploader") or info.get("channel"),
        duration=None if info.get("is_live") else info.get("duration"),
        thumbnail=info.get("thumbnail"),
    )


def download(url: str, selector: str, container: str, outdir: str, emit: Emit) -> Downloaded:
    """Download every stream ``selector`` picks, in parallel, and mux them into ``container``.

    A rejected media URL (HTTP 403, normally an expired signature) is refreshed
    and retried once. Raises ``yt_dlp.utils.DownloadError`` on failure.
    """
    for attempt in range(2):
        directory = os.path.join(outdir, f"attempt-{attempt}")
        os.makedirs(directory)
        try:
            return _download(url, selector, container, directory, emit)
        except DownloadError as exc:
            if "HTTP Error 403" not in str(exc):
                raise
            _forget(url)
            if attempt:
                raise DownloadError(
                    "YouTube rejected the media download (HTTP 403) even after refreshing "
                    "the link. Update yt-dlp and make sure Node 22+ or Deno is available."
                ) from exc
            emit({"phase": "process", "step": "retry"})
    raise AssertionError("unreachable")


def download_proxy(url: str, outdir: str, emit: Emit) -> str:
    """Fetch a small editing proxy and return a browser-playable MP4 path."""
    result = download(url, PROXY_FORMAT, "mp4", outdir, emit)
    return media.prepare_preview(result.filepath, outdir, emit)


# --------------------------------------------------------------------------- #
# Internals
# --------------------------------------------------------------------------- #
def _ydl_opts(**extra: Any) -> dict[str, Any]:
    return {
        "noplaylist": True,
        "quiet": True,
        "no_warnings": False,  # keep extractor warnings in the server log
        "js_runtimes": {"deno": {}, "node": {}},
        **extra,
    }


def _download(url: str, selector: str, container: str, directory: str, emit: Emit) -> Downloaded:
    source = _source_info(url)
    # extract_info already ran a default format selection; drop it so ours applies.
    source.pop("requested_formats", None)
    source.pop("requested_downloads", None)
    with YoutubeDL(_ydl_opts(format=selector)) as ydl:
        selected = ydl.process_ie_result(copy.deepcopy(source), download=False)
    formats = selected.get("requested_formats") or [selected]
    progress = _Progress(formats, emit)

    def fetch(index: int) -> media.Stream:
        fmt = formats[index]
        stream_dir = os.path.join(directory, str(index))
        os.makedirs(stream_dir)
        opts = _ydl_opts(
            format=fmt["format_id"],
            outtmpl=os.path.join(stream_dir, "%(id)s.%(ext)s"),
            noprogress=True,
            overwrites=True,
            concurrent_fragment_downloads=8,
            progress_hooks=[lambda d: progress.update(index, d)],
        )
        with YoutubeDL(opts) as ydl:
            info = ydl.process_ie_result(copy.deepcopy(source), download=True)
        return media.Stream(
            _final_filepath(info, stream_dir), video=_has(fmt, "vcodec"), audio=_has(fmt, "acodec")
        )

    with ThreadPoolExecutor(max_workers=len(formats)) as pool:
        streams = list(pool.map(fetch, range(len(formats))))

    emit({"phase": "process", "step": "merge"})
    out = os.path.join(directory, f"source.{container}")
    media.mux(streams, out)
    for stream in streams:
        os.remove(stream.path)
    return Downloaded(filepath=out, title=source.get("title") or "video", ext=container)


class _Progress:
    """Aggregate per-stream yt-dlp progress hooks into one throttled event."""

    def __init__(self, formats: list[dict[str, Any]], emit: Emit) -> None:
        self._formats = formats
        self._emit = emit
        self._state: dict[int, dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._last = 0.0

    def update(self, index: int, d: dict[str, Any]) -> None:
        item = {
            "status": d.get("status"),  # downloading | finished | error
            "downloaded": d.get("downloaded_bytes"),
            "total": d.get("total_bytes") or d.get("total_bytes_estimate"),
            "speed": d.get("speed"),
        }
        with self._lock:
            self._state[index] = item
            now = time.monotonic()
            if item["status"] == "downloading" and now - self._last < _PROGRESS_INTERVAL:
                return
            self._last = now
            self._emit(self._event())

    def _event(self) -> dict[str, Any]:
        streams = []
        for i, fmt in enumerate(self._formats):
            s = self._state.get(i, {})
            status = s.get("status") or "pending"
            streams.append(
                {
                    "id": str(i),
                    "label": _label(fmt),
                    "status": status,
                    "percent": 100.0 if status == "finished" else _percent(s),
                    "downloaded": s.get("downloaded"),
                    "total": s.get("total"),
                }
            )
        items = list(self._state.values())
        known = len(items) == len(self._formats) and all(i["total"] for i in items)
        total = sum(i["total"] for i in items) if known else None
        downloaded = sum(i["downloaded"] or 0 for i in items)
        speed = sum(i["speed"] or 0 for i in items if i["status"] == "downloading") or None
        return {
            "phase": "download",
            "streams": streams,
            "downloaded": downloaded,
            "total": total,
            "speed": speed,
            "eta": max(0.0, total - downloaded) / speed if total and speed else None,
            "percent": min(100.0, downloaded / total * 100) if total else None,
        }


def _percent(item: dict[str, Any]) -> float | None:
    total, downloaded = item.get("total"), item.get("downloaded")
    if not total or downloaded is None:
        return None
    return max(0.0, min(100.0, downloaded / total * 100))


def _has(fmt: dict[str, Any], key: str) -> bool:
    return fmt.get(key) not in (None, "none")


def _label(fmt: dict[str, Any]) -> str:
    video, audio = _has(fmt, "vcodec"), _has(fmt, "acodec")
    return "Video + audio" if video and audio else "Video" if video else "Audio"


def _final_filepath(info: dict[str, Any], directory: str) -> str:
    """Locate the finished file; fall back to scanning the single-stream directory."""
    for dl in info.get("requested_downloads") or []:
        fp = dl.get("filepath")
        if fp and os.path.exists(fp):
            return fp
    candidates = [
        os.path.join(directory, name)
        for name in os.listdir(directory)
        if not name.endswith((".part", ".ytdl"))
    ]
    if not candidates:
        raise FileNotFoundError("Download finished but no output file was found.")
    return max(candidates, key=os.path.getsize)


# Short-lived, bounded extraction cache. The info preview, the source download
# and the proxy download all share one yt-dlp extraction, including concurrent
# requests for the same URL. Callers receive private deep copies.
_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_inflight: dict[str, Future[dict[str, Any]]] = {}
_lock = threading.Lock()


def _source_info(url: str) -> dict[str, Any]:
    with _lock:
        now = time.monotonic()
        for key, (created, _) in list(_cache.items()):
            if now - created > _INFO_TTL:
                del _cache[key]
        if url in _cache:
            return copy.deepcopy(_cache[url][1])
        future = _inflight.get(url)
        owner = future is None
        if owner:
            future = _inflight[url] = Future()
    if not owner:
        return copy.deepcopy(future.result())
    try:
        with YoutubeDL(_ydl_opts()) as ydl:
            info = ydl.extract_info(url, download=False)
        if not info or info.get("_type") in ("playlist", "multi_video"):
            raise ValueError("Please paste a link to a single video.")
        with _lock:
            if len(_cache) >= _INFO_CACHE_SIZE:
                del _cache[next(iter(_cache))]
            _cache[url] = (time.monotonic(), copy.deepcopy(info))
        future.set_result(info)
        return copy.deepcopy(info)
    except Exception as exc:
        future.set_exception(exc)
        raise
    finally:
        with _lock:
            _inflight.pop(url, None)


def _forget(url: str) -> None:
    with _lock:
        _cache.pop(url, None)
