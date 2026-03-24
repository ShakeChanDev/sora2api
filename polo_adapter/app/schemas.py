"""Request and response schemas."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator


class VideoCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt: str
    image_url: str | None = None
    model: str = "sora-2-portrait-15s"
    style: str | None = None
    references: list[str] | None = None

    @field_validator("prompt")
    @classmethod
    def validate_prompt(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("prompt is required")
        return value

    @field_validator("image_url")
    @classmethod
    def validate_image_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @field_validator("model")
    @classmethod
    def validate_model(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("model cannot be empty")
        return value

    @field_validator("style")
    @classmethod
    def validate_style(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None


class VideoCreateResponse(BaseModel):
    id: str
    object: Literal["video.generation"]
    created: int
    model: str
    status: Literal["pending"]


class VideoGenerationResponse(BaseModel):
    id: str
    status: Literal["pending", "processing", "success", "failed"]
    progress: int
    video_url: str | None
    error_message: str | None
    created_at: int | None
    completed_at: int | None
