"""Request/response schemas and the enums that drive format selection."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, field_validator, model_validator


class MediaType(str, Enum):
    audio = "audio"
    video = "video"


class Mode(str, Enum):
    quality = "quality"
    compatibility = "compatibility"


class JobStatus(str, Enum):
    running = "running"
    completed = "completed"
    error = "error"


class PreviewRequest(BaseModel):
    url: str

    @field_validator("url")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("A YouTube link is required.")
        return v


class ExportRequest(BaseModel):
    media_type: MediaType = MediaType.video
    mode: Mode = Mode.compatibility
    start_time: float = Field(default=0, ge=0, allow_inf_nan=False)
    end_time: float | None = Field(default=None, gt=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def _valid_interval(self) -> ExportRequest:
        if self.end_time is not None and self.end_time <= self.start_time:
            raise ValueError("End time must be after start time.")
        return self


class JobCreated(BaseModel):
    id: str


class MediaInfo(BaseModel):
    """Lightweight metadata shown before anything is downloaded."""

    title: str | None = None
    uploader: str | None = None
    duration: float | None = None  # seconds; None for live streams
    thumbnail: str | None = None


# The output container for each (type, mode) export choice. The UI mirrors this.
OUTPUT_CONTAINER: dict[tuple[MediaType, Mode], str] = {
    (MediaType.audio, Mode.quality): "opus",
    (MediaType.audio, Mode.compatibility): "m4a",
    (MediaType.video, Mode.quality): "mkv",
    (MediaType.video, Mode.compatibility): "mp4",
}

# MIME types used when streaming a finished file back to the browser.
CONTENT_TYPES: dict[str, str] = {
    "opus": "audio/ogg",
    "m4a": "audio/mp4",
    "mkv": "video/x-matroska",
    "mp4": "video/mp4",
}
