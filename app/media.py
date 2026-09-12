"""ffmpeg/ffprobe helpers: probing, lossless muxing, preview proxies and exports.

Everything here is blocking and framework-agnostic. ``jobs.py`` runs it in
worker threads and forwards the ``emit`` events to the browser.
"""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .models import OUTPUT_CONTAINER, ExportRequest, MediaType, Mode

# A JSON-serializable progress event handed to the caller.
Emit = Callable[[dict[str, Any]], None]

# Selections within this many seconds of both ends count as the whole video,
# which lets the export copy the original streams instead of re-encoding.
WHOLE_TOLERANCE = 0.05

_X264 = ["-c:v", "libx264", "-preset", "fast", "-crf", "18", "-pix_fmt", "yuv420p"]
_PREVIEW_SCALE = (
    "scale=w='min(1280,iw)':h='min(720,ih)':force_original_aspect_ratio=decrease:force_divisible_by=2"
)


@dataclass(frozen=True)
class Probe:
    """The facts about a media file that decide how it can be exported."""

    duration: float
    video: str | None  # ffprobe codec name, e.g. "h264", "vp9", "av1"
    audio: str | None  # e.g. "aac", "opus"
    pix_fmt: str | None = None
    audio_profile: str | None = None


@dataclass(frozen=True)
class Stream:
    """One downloaded elementary stream, ready to be muxed."""

    path: str
    video: bool
    audio: bool


def probe(path: str) -> Probe:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", path],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    info = json.loads(out)
    video = next((s for s in info["streams"] if s["codec_type"] == "video"), None)
    audio = next((s for s in info["streams"] if s["codec_type"] == "audio"), None)
    return Probe(
        duration=float(info["format"].get("duration") or 0),
        video=video.get("codec_name") if video else None,
        audio=audio.get("codec_name") if audio else None,
        pix_fmt=video.get("pix_fmt") if video else None,
        audio_profile=audio.get("profile") if audio else None,
    )


def mux(streams: list[Stream], out: str) -> None:
    """Copy the first video and first audio stream into ``out`` without re-encoding."""
    args: list[str] = []
    for stream in streams:
        args += ["-i", stream.path]
    video = next((i for i, s in enumerate(streams) if s.video), None)
    audio = next((i for i, s in enumerate(streams) if s.audio), None)
    if video is not None:
        args += ["-map", f"{video}:v:0"]
    if audio is not None:
        args += ["-map", f"{audio}:a:0"]
    run_ffmpeg([*args, "-c", "copy", *_faststart(out), out])


def prepare_preview(source: str, tmpdir: str, emit: Emit) -> str:
    """Return a browser-playable MP4 for ``source``: reuse it, remux, or (last) re-encode."""
    info = probe(source)
    if info.video is None:
        raise ValueError("This video has no video stream to preview.")
    copy_video = info.video == "h264" and info.pix_fmt == "yuv420p"
    copy_audio = info.audio is None or (info.audio == "aac" and info.audio_profile == "LC")
    if copy_video and copy_audio and source.lower().endswith(".mp4"):
        return source  # already written with +faststart by mux()

    emit({"phase": "process", "step": "preview"})
    out = os.path.join(tmpdir, "preview.mp4")
    args = ["-i", source, "-map", "0:v:0", "-map", "0:a:0?"]
    if copy_video:
        args += ["-c:v", "copy"]
    else:
        args += [
            "-vf",
            _PREVIEW_SCALE,
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            "24",
            "-pix_fmt",
            "yuv420p",
        ]
    args += ["-c:a", "copy"] if copy_audio else ["-c:a", "aac", "-b:a", "128k"]
    run_ffmpeg([*args, "-movflags", "+faststart", out])
    return out


def lossless_containers(info: Probe) -> list[str]:
    """Output containers a whole-video export can reach by pure stream copy."""
    result = []
    for (media_type, _), ext in OUTPUT_CONTAINER.items():
        copy_video, copy_audio = _copy_plan(ext, media_type, info)
        if copy_audio and (copy_video or media_type is MediaType.audio):
            result.append(ext)
    return result


def export_clip(source: str, info: Probe, req: ExportRequest, tmpdir: str, emit: Emit) -> str:
    """Write the requested export of ``source`` into ``tmpdir`` and return its path.

    Whole-video exports copy any stream the target container accepts. Trimmed
    exports are re-encoded so the cut lands exactly on the requested times.
    """
    if req.media_type is MediaType.audio and info.audio is None:
        raise ValueError("This video has no audio track.")
    ext = OUTPUT_CONTAINER[(req.media_type, req.mode)]
    out = os.path.join(tmpdir, f"clip.{ext}")
    start = req.start_time
    end = req.end_time if req.end_time is not None else info.duration
    whole = start <= WHOLE_TOLERANCE and end >= info.duration - WHOLE_TOLERANCE
    copy_video, copy_audio = _copy_plan(ext, req.media_type, info) if whole else (False, False)

    args = [] if whole else ["-ss", f"{start:.3f}"]
    args += ["-i", source]
    if not whole:
        args += ["-t", f"{end - start:.3f}"]
    if req.media_type is MediaType.video:
        args += ["-map", "0:v:0", "-map", "0:a:0?"]
        args += ["-c:v", "copy"] if copy_video else _X264
    else:
        args += ["-map", "0:a:0", "-vn"]
    if copy_audio:
        args += ["-c:a", "copy"]
    else:
        args += ["-c:a", "libopus" if req.mode is Mode.quality else "aac", "-b:a", "192k"]

    step = "trim" if not whole else "remux" if ext in lossless_containers(info) else "convert"
    emit({"phase": "process", "step": step})
    run_ffmpeg([*args, *_faststart(out), out])
    return out


def run_ffmpeg(args: list[str]) -> None:
    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args],
        capture_output=True,
        text=True,
    )
    if result.returncode:
        raise RuntimeError(f"ffmpeg failed: {result.stderr.strip()[-1500:]}")


def _copy_plan(ext: str, media_type: MediaType, info: Probe) -> tuple[bool, bool]:
    """Whether the (video, audio) streams may be stream-copied into ``ext``."""
    video = media_type is MediaType.video and (ext == "mkv" or (ext == "mp4" and info.video == "h264"))
    audio = (
        ext == "mkv"
        or (ext in ("mp4", "m4a") and info.audio == "aac")
        or (ext == "opus" and info.audio == "opus")
    )
    return video, audio


def _faststart(path: str) -> list[str]:
    """Move the MP4 index to the front so browsers can start playing immediately."""
    return ["-movflags", "+faststart"] if path.endswith((".mp4", ".m4a")) else []
