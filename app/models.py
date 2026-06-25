"""Request/response schemas and the enums that drive format selection."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, field_validator


class MediaType(str, Enum):
    audio = "audio"
    video = "video"


class Mode(str, Enum):
    quality = "quality"
    compatibility = "compatibility"


class JobStatus(str, Enum):
    pending = "pending"
    downloading = "downloading"
    processing = "processing"  # ffmpeg merge / audio extraction
    completed = "completed"
    error = "error"


class JobRequest(BaseModel):
    url: str
    media_type: MediaType
    mode: Mode

    @field_validator("url")
    @classmethod
    def _non_empty_url(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("A YouTube link is required.")
        return v


class JobCreated(BaseModel):
    id: str


class MediaInfo(BaseModel):
    """Lightweight metadata shown as a preview before downloading."""

    title: str | None = None
    uploader: str | None = None
    duration: int | None = None  # seconds
    thumbnail: str | None = None


# --- The resolved output container for each (type, mode) combination. ---
# Kept here so the backend and the UI agree on what a selection produces.
OUTPUT_CONTAINER: dict[tuple[MediaType, Mode], str] = {
    (MediaType.audio, Mode.quality): "opus",
    (MediaType.audio, Mode.compatibility): "m4a",
    (MediaType.video, Mode.quality): "mkv",
    (MediaType.video, Mode.compatibility): "mp4",
}

# MIME types used when streaming the finished file back to the browser.
CONTENT_TYPES: dict[str, str] = {
    "opus": "audio/ogg",
    "m4a": "audio/mp4",
    "mp3": "audio/mpeg",
    "mkv": "video/x-matroska",
    "webm": "video/webm",
    "mp4": "video/mp4",
}
