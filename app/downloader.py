"""yt-dlp integration: format selection, metadata lookup, and the download run.

This module is deliberately framework-agnostic. It knows nothing about FastAPI
or asyncio — it just takes a request, a temp directory, and an ``emit`` callback
that it pushes normalized progress events through. ``jobs.py`` is responsible for
bridging those callbacks onto the event loop.
"""

from __future__ import annotations

import os
import json
import copy
import subprocess
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from collections.abc import Callable
from typing import Any

from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

from .models import JobRequest, MediaInfo, MediaType, Mode, OUTPUT_CONTAINER

# An event is a small, JSON-serializable dict handed to the emit callback.
Emit = Callable[[dict[str, Any]], None]


def _common_opts() -> dict[str, Any]:
    return {
        "noplaylist": True,
        "quiet": True,
        # Keep extractor warnings in server logs for diagnosing YouTube changes.
        "no_warnings": False,
        "js_runtimes": {"deno": {}, "node": {}},
    }


def build_ydl_opts(req: JobRequest, tmpdir: str, emit: Emit) -> dict[str, Any]:
    """Translate a (media_type, mode) selection into yt-dlp options.

    The four combinations map to:
      audio + quality        -> bestaudio, remuxed to native Opus (.opus)
      audio + compatibility  -> native AAC if available, as .m4a
      video + quality        -> best video + best audio muxed into .mkv (no re-encode)
      video + compatibility  -> H.264 + AAC muxed into .mp4 (plays anywhere)
    """
    opts: dict[str, Any] = {
        **_common_opts(),
        "outtmpl": os.path.join(tmpdir, "%(title).180B [%(id)s].%(ext)s"),
        "noprogress": True,
        "overwrites": True,
        "concurrent_fragment_downloads": 8,
        "progress_hooks": [lambda d: emit(_download_event(d))],
        "postprocessor_hooks": [lambda d: emit(_postprocess_event(d))],
    }

    if req.media_type is MediaType.audio:
        if req.mode is Mode.quality:
            opts["format"] = "bestaudio/best"
            # Source audio is already Opus on YouTube, so this remuxes (copy) into
            # an Ogg/Opus container rather than re-encoding.
            opts["postprocessors"] = [
                {"key": "FFmpegExtractAudio", "preferredcodec": "opus"}
            ]
        else:  # compatibility -> .m4a (AAC)
            opts["format"] = "bestaudio[ext=m4a]/bestaudio/best"
            opts["postprocessors"] = [
                {"key": "FFmpegExtractAudio", "preferredcodec": "m4a"}
            ]
    else:  # video
        if req.mode is Mode.quality:
            # Best available video (often AV1/VP9) + best audio (Opus), losslessly
            # muxed into Matroska which accepts any codec combination.
            opts["format"] = "bestvideo+bestaudio/best"
            opts["merge_output_format"] = "mkv"
        else:  # compatibility -> .mp4 (H.264 + AAC)
            opts["format"] = (
                "bestvideo[vcodec^=avc1]+bestaudio[ext=m4a]/"
                "bestvideo[ext=mp4]+bestaudio[ext=m4a]/"
                "best[ext=mp4]/best"
            )
            opts["merge_output_format"] = "mp4"

    return opts


def run_download(req: JobRequest, tmpdir: str, emit: Emit, *, format_selector: str | None = None) -> dict[str, Any]:
    """Run the blocking download. Returns the final file path, title and ext.

    Raises whatever yt-dlp raises (typically ``yt_dlp.utils.DownloadError``);
    the caller is expected to translate that into an error event.
    """
    for attempt in range(2):
        directory = os.path.join(tmpdir, f"attempt-{attempt}")
        os.makedirs(directory)
        try:
            return _run_download(req, directory, emit, format_selector=format_selector)
        except DownloadError as exc:
            if "HTTP Error 403" not in str(exc):
                raise
            with _cache_lock:
                _cache.pop(req.url, None)
            if attempt:
                raise DownloadError(
                    "YouTube rejected the media download (HTTP 403), even after refreshing "
                    "the link. Check the server logs for JavaScript challenge warnings; "
                    "update yt-dlp and verify Node 22+ or Deno is available."
                ) from exc
            emit({"phase": "postprocess", "status": "started", "postprocessor": "Refresh"})
            # All stream workers have stopped before retrying. Isolated directories
            # prevent partial files from the rejected URLs contaminating the retry.
    raise RuntimeError("Download attempts exhausted.")


def _run_download(req: JobRequest, tmpdir: str, emit: Emit, *, format_selector: str | None = None) -> dict[str, Any]:
    source = copy.deepcopy(_source_info(req.url))
    # extract_info includes a default selection. Re-select for this request;
    # otherwise its requested_formats can leak into individual stream workers.
    source.pop("requested_formats", None)
    source.pop("requested_downloads", None)
    duration = source.get("duration")
    cropped = req.start_time > 0 or req.end_time is not None
    if cropped:
        if source.get("is_live") or not duration:
            raise ValueError("Trimming requires a finished video with a known duration.")
        if req.start_time >= duration or (req.end_time is not None and req.end_time > duration):
            raise ValueError("The selected interval is outside the video duration.")

    opts = build_ydl_opts(req, tmpdir, emit)
    if format_selector:
        opts["format"] = format_selector
    with YoutubeDL(opts) as ydl:
        selected = ydl.process_ie_result(copy.deepcopy(source), download=False)
    formats = selected.get("requested_formats") or [selected]
    progress: dict[int, dict[str, Any]] = {}
    lock = threading.Lock()

    def report(index: int, event: dict[str, Any]) -> None:
        if event["phase"] != "download":
            return
        with lock:
            progress[index] = event
            events = list(progress.values())
            known = len(events) == len(formats) and all(e.get("total") for e in events)
            total = sum(e.get("total") or 0 for e in events) if known else None
            downloaded = sum(e.get("downloaded") or 0 for e in events)
            speed = sum(e.get("speed") or 0 for e in events if e.get("status") != "finished")
            streams = []
            for i, fmt in enumerate(formats):
                item = progress.get(i, {})
                video = fmt.get("vcodec") not in (None, "none")
                audio = fmt.get("acodec") not in (None, "none")
                streams.append({
                    "id": str(i), "label": "Video + audio" if video and audio else "Video" if video else "Audio",
                    "status": item.get("status", "pending"),
                    "percent": 100 if item.get("status") == "finished" else item.get("percent"),
                    "downloaded": item.get("downloaded"), "total": item.get("total"),
                })
            emit({"phase": "download", "status": "downloading", "streams": streams,
                  "downloaded": downloaded, "total": total, "speed": speed or None,
                  "eta": max(0, total - downloaded) / speed if total and speed else None,
                  "percent": min(100, downloaded / total * 100) if total else None})

    def download_stream(index: int) -> str:
        directory = os.path.join(tmpdir, str(index))
        os.makedirs(directory)
        stream_opts = build_ydl_opts(req, directory, lambda e: report(index, e))
        stream_opts["format"] = formats[index]["format_id"]
        stream_opts.pop("postprocessors", None)
        with YoutubeDL(stream_opts) as ydl:
            info = ydl.process_ie_result(copy.deepcopy(source), download=True)
        return _final_filepath(info, directory)

    with ThreadPoolExecutor(max_workers=len(formats)) as pool:
        paths = list(pool.map(download_stream, range(len(formats))))

    ext = OUTPUT_CONTAINER[(req.media_type, req.mode)]
    filepath = os.path.join(tmpdir, f"output.{ext}")
    emit({"phase": "postprocess", "status": "started",
          "postprocessor": "Trim" if cropped else "ExtractAudio" if req.media_type is MediaType.audio else "Merger"})
    args = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
    for path in paths:
        if cropped:
            args += ["-ss", str(req.start_time)]
        args += ["-i", path]
    if req.media_type is MediaType.audio:
        args += ["-map", "0:a:0", "-vn"]
    else:
        audio_index = next((i for i, f in enumerate(formats) if f.get("acodec") not in (None, "none")), 0)
        args += ["-map", "0:v:0", "-map", f"{audio_index}:a:0?"]
    if cropped:
        args += ["-t", str((req.end_time or duration) - req.start_time)]
        if req.media_type is MediaType.video:
            args += ["-c:v", "libx264", "-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p"]
        args += ["-c:a", "libopus" if req.mode is Mode.quality else "aac", "-b:a", "192k"]
    elif req.media_type is MediaType.audio:
        codec = formats[0].get("acodec") or ""
        native = codec.startswith("opus") if ext == "opus" else codec.startswith(("aac", "mp4a"))
        args += ["-c:a", "copy" if native else ("libopus" if ext == "opus" else "aac")]
    else:
        args += ["-c", "copy"]
    if ext in ("mp4", "m4a"):
        args += ["-movflags", "+faststart"]
    result = subprocess.run([*args, filepath], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f"Could not finalize media: {result.stderr.strip()[-1500:]}")
    for path in paths:
        os.remove(path)
    return {"filepath": filepath, "title": source.get("title") or "download", "ext": ext}


# Short-lived bounded cache: preview and download share one extraction, including
# simultaneous requests for the same URL. Copies isolate yt-dlp's mutations.
_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_inflight: dict[str, Future] = {}
_cache_lock = threading.Lock()


def _source_info(url: str) -> dict[str, Any]:
    with _cache_lock:
        now = time.monotonic()
        for key, (created, _) in list(_cache.items()):
            if now - created > 300:
                del _cache[key]
        if url in _cache:
            return copy.deepcopy(_cache[url][1])
        owner = url not in _inflight
        future = _inflight.setdefault(url, Future())
    if not owner:
        return copy.deepcopy(future.result())
    try:
        with YoutubeDL(_common_opts()) as ydl:
            info = ydl.extract_info(url, download=False)
        if not info or info.get("_type") in ("playlist", "multi_video"):
            raise ValueError("Please paste a link to a single video.")
        with _cache_lock:
            if len(_cache) >= 32:
                del _cache[next(iter(_cache))]
            _cache[url] = (time.monotonic(), copy.deepcopy(info))
        future.set_result(info)
        return copy.deepcopy(info)
    except Exception as exc:
        future.set_exception(exc)
        raise
    finally:
        with _cache_lock:
            _inflight.pop(url, None)


def fetch_info(url: str) -> MediaInfo:
    """Resolve metadata and retain extraction for the subsequent download."""
    info = _source_info(url)
    return MediaInfo(
        title=info.get("title"),
        uploader=info.get("uploader") or info.get("channel"),
        duration=None if info.get("is_live") else info.get("duration"),
        thumbnail=info.get("thumbnail"),
    )


# --------------------------------------------------------------------------- #
# Internal helpers
# --------------------------------------------------------------------------- #
def _final_filepath(info: dict[str, Any], tmpdir: str) -> str:
    """Locate the finished file after merging/post-processing.

    yt-dlp records the post-processed path on ``requested_downloads``; fall back
    to scanning the (single-job) temp directory if that's somehow missing.
    """
    for dl in info.get("requested_downloads") or []:
        fp = dl.get("filepath")
        if fp and os.path.exists(fp):
            return fp

    candidates = [
        os.path.join(tmpdir, name)
        for name in os.listdir(tmpdir)
        if not name.endswith((".part", ".ytdl"))
    ]
    if not candidates:
        raise FileNotFoundError("Download finished but no output file was found.")
    return max(candidates, key=os.path.getsize)


def _download_event(d: dict[str, Any]) -> dict[str, Any]:
    """Project a yt-dlp progress dict down to a small serializable event."""
    total = d.get("total_bytes") or d.get("total_bytes_estimate")
    downloaded = d.get("downloaded_bytes")
    percent: float | None = None
    if total and downloaded is not None and total > 0:
        percent = max(0.0, min(100.0, downloaded / total * 100))
    return {
        "phase": "download",
        "status": d.get("status"),  # downloading | finished | error
        "downloaded": downloaded,
        "total": total,
        "speed": d.get("speed"),
        "eta": d.get("eta"),
        "percent": percent,
    }


def _postprocess_event(d: dict[str, Any]) -> dict[str, Any]:
    """Project a yt-dlp postprocessor hook dict down to a small event."""
    return {
        "phase": "postprocess",
        "status": d.get("status"),  # started | processing | finished
        "postprocessor": d.get("postprocessor"),
    }


def prepare_preview(filepath: str, tmpdir: str, emit: Emit) -> tuple[str, float]:
    """Reuse browser-compatible media, remux if needed, and encode only as fallback."""
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format",
                            "-of", "json", filepath], capture_output=True, text=True, check=True)
    info = json.loads(probe.stdout)
    video = next((s for s in info["streams"] if s["codec_type"] == "video"), None)
    audio = next((s for s in info["streams"] if s["codec_type"] == "audio"), None)
    if video is None:
        raise ValueError("This source does not contain a video preview.")
    duration = float(info["format"]["duration"])
    copy_video = video.get("codec_name") == "h264" and video.get("pix_fmt") == "yuv420p"
    copy_audio = audio is None or (audio.get("codec_name") == "aac" and audio.get("profile") == "LC")
    # Our MP4 downloader has already written +faststart for browser playback.
    if copy_video and copy_audio and os.path.splitext(filepath)[1].lower() == ".mp4":
        return filepath, duration

    emit({"phase": "postprocess", "status": "started",
          "postprocessor": "PreviewRemux" if copy_video else "Preview"})
    preview = os.path.join(tmpdir, "preview.mp4")
    args = ["-i", filepath, "-map", "0:v:0", "-map", "0:a:0?"]
    if copy_video:
        args += ["-c:v", "copy"]
    else:
        args += ["-vf", "scale=w='min(1280,iw)':h='min(720,ih)':force_original_aspect_ratio=decrease:force_divisible_by=2",
                 "-c:v", "libx264", "-preset", "ultrafast", "-crf", "24", "-pix_fmt", "yuv420p"]
    args += ["-c:a", "copy"] if copy_audio else ["-c:a", "aac", "-b:a", "128k"]
    _ffmpeg([*args, "-movflags", "+faststart", preview])
    return preview, duration


def export_selection(req: JobRequest, source: str, duration: float, tmpdir: str, emit: Emit) -> dict[str, Any]:
    end = req.end_time if req.end_time is not None else duration
    if req.start_time >= duration or end > duration or end <= req.start_time:
        raise ValueError("The selected interval is outside the video duration.")
    emit({"phase": "postprocess", "status": "started", "postprocessor": "Trim"})
    ext = OUTPUT_CONTAINER[(req.media_type, req.mode)]
    filepath = os.path.join(tmpdir, f"selection.{ext}")
    args = ["-ss", str(req.start_time), "-i", source, "-t", str(end - req.start_time)]
    if req.media_type is MediaType.video:
        args += ["-map", "0:v:0", "-map", "0:a:0?", "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p"]
    else:
        args += ["-map", "0:a:0", "-vn"]
    args += ["-c:a", "libopus" if req.mode is Mode.quality else "aac", "-b:a", "192k"]
    if ext in ("mp4", "m4a"):
        args += ["-movflags", "+faststart"]
    _ffmpeg([*args, filepath])
    return {"filepath": filepath, "ext": ext}


def _ffmpeg(args: list[str]) -> None:
    result = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f"Could not prepare media: {result.stderr.strip()[-1500:]}")


def download_preview(url: str, tmpdir: str, emit: Emit) -> tuple[str, float]:
    """Fetch a small editing proxy while the original source downloads."""
    directory = os.path.join(tmpdir, "editing-proxy")
    os.makedirs(directory)
    result = run_download(
        JobRequest(url=url, media_type=MediaType.video, mode=Mode.compatibility),
        directory, emit,
        format_selector=("bestvideo[vcodec^=avc1][height<=720]+bestaudio[ext=m4a]/"
                         "best[vcodec^=avc1][height<=720]/"
                         "bestvideo[height<=720]+bestaudio/best[height<=720]/best"),
    )
    return prepare_preview(result["filepath"], directory, emit)
