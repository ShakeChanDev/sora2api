"""Schemas for adapter API and readonly database rows."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from pydantic import BaseModel, ConfigDict, StrictStr, field_validator


class VideoCreateRequest(BaseModel):
    """Polo-compatible create request."""

    model_config = ConfigDict(extra="forbid")

    prompt: StrictStr
    image_url: Optional[StrictStr] = None
    model: Optional[StrictStr] = None
    style: Optional[StrictStr] = None
    references: Optional[list[StrictStr]] = None

    @field_validator("prompt")
    @classmethod
    def validate_prompt(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("prompt is required")
        return normalized

    @field_validator("image_url")
    @classmethod
    def validate_image_url(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("image_url must be a non-empty string")
        return normalized

    @field_validator("model")
    @classmethod
    def validate_model(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("model must be a non-empty string")
        return normalized

    @field_validator("references", mode="before")
    @classmethod
    def ensure_reference_array(cls, value):
        if value is None:
            return None
        if not isinstance(value, list):
            raise ValueError("references must be an array of strings")
        return value

    @field_validator("references")
    @classmethod
    def ensure_reference_items(cls, value: Optional[list[str]]) -> Optional[list[str]]:
        if value is None:
            return None
        for item in value:
            if not isinstance(item, str) or not item.strip():
                raise ValueError("references must be an array of strings")
        return value


class VideoCreateResponse(BaseModel):
    """Polo-compatible create response."""

    id: str
    object: str = "video.generation"
    created: int
    model: str
    status: str = "pending"


class VideoStatusResponse(BaseModel):
    """Polo-compatible task status response."""

    id: str
    status: str
    progress: float
    video_url: Optional[str] = None
    error_message: Optional[str] = None
    created_at: Optional[int] = None
    completed_at: Optional[int] = None


@dataclass(slots=True)
class TaskRecord:
    """Readonly row from the main service tasks table."""

    task_id: str
    status: str
    progress: float
    result_urls: Optional[str]
    error_message: Optional[str]
    created_at: Optional[str]
    completed_at: Optional[str]


@dataclass(slots=True)
class RequestLogRecord:
    """Readonly row from the main service request_logs table."""

    task_id: str
    response_body: Optional[str]
    status_code: Optional[int]
    created_at: Optional[str]
    updated_at: Optional[str]
