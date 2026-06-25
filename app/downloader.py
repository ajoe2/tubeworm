"""yt-dlp integration: format selection, metadata lookup, and the download run.

This module is deliberately framework-agnostic. It knows nothing about FastAPI
or asyncio — it just takes a request, a temp directory, and an ``emit`` callback
that it pushes normalized progress events through. ``jobs.py`` is responsible for
bridging those callbacks onto the event loop.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

from yt_dlp import YoutubeDL

from .models import JobRequest, MediaInfo, MediaType, Mode

# An event is a small, JSON-serializable dict handed to the emit callback.
Emit = Callable[[dict[str, Any]], None]


def build_ydl_opts(req: JobRequest, tmpdir: str, emit: Emit) -> dict[str, Any]:
    """Translate a (media_type, mode) selection into yt-dlp options.

    The four combinations map to:
      audio + quality        -> bestaudio, remuxed to native Opus (.opus)
      audio + compatibility  -> native AAC if available, as .m4a
      video + quality        -> best video + best audio muxed into .mkv (no re-encode)
      video + compatibility  -> H.264 + AAC muxed into .mp4 (plays anywhere)
    """
    opts: dict[str, Any] = {
        "outtmpl": os.path.join(tmpdir, "%(title).180B [%(id)s].%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "overwrites": True,
        "concurrent_fragment_downloads": 4,
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


def run_download(req: JobRequest, tmpdir: str, emit: Emit) -> dict[str, Any]:
    """Run the blocking download. Returns the final file path, title and ext.

    Raises whatever yt-dlp raises (typically ``yt_dlp.utils.DownloadError``);
    the caller is expected to translate that into an error event.
    """
    opts = build_ydl_opts(req, tmpdir, emit)
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(req.url, download=True)
        if info.get("entries"):  # defensive: a playlist slipped through
            info = info["entries"][0]

    filepath = _final_filepath(info, tmpdir)
    return {
        "filepath": filepath,
        "title": info.get("title") or "download",
        "ext": os.path.splitext(filepath)[1].lstrip(".").lower(),
    }


def fetch_info(url: str) -> MediaInfo:
    """Resolve lightweight metadata for the URL without downloading media."""
    opts = {
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
    }
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    if info.get("entries"):
        info = info["entries"][0]
    return MediaInfo(
        title=info.get("title"),
        uploader=info.get("uploader") or info.get("channel"),
        duration=info.get("duration"),
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
