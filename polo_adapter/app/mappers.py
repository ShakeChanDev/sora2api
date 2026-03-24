"""Mapping helpers for public API and SQLite records."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from .errors import AdapterError

DEFAULT_EXTERNAL_MODEL = "sora-2-portrait-15s"


@dataclass(frozen=True)
class ModelMetadata:
    external_name: str
    internal_name: str
    references_supported: bool = True


MODEL_REGISTRY: dict[str, ModelMetadata] = {
    "sora-2-portrait-10s": ModelMetadata("sora-2-portrait-10s", "sora2-portrait-10s"),
    "sora-2-landscape-10s": ModelMetadata("sora-2-landscape-10s", "sora2-landscape-10s"),
    "sora-2-portrait-15s": ModelMetadata("sora-2-portrait-15s", "sora2-portrait-15s"),
    "sora-2-landscape-15s": ModelMetadata("sora-2-landscape-15s", "sora2-landscape-15s"),
    "sora-2-portrait-25s": ModelMetadata("sora-2-portrait-25s", "sora2-portrait-25s"),
    "sora-2-landscape-25s": ModelMetadata("sora-2-landscape-25s", "sora2-landscape-25s"),
    "sora-2-pro-portrait-10s": ModelMetadata("sora-2-pro-portrait-10s", "sora2pro-portrait-10s"),
    "sora-2-pro-landscape-10s": ModelMetadata("sora-2-pro-landscape-10s", "sora2pro-landscape-10s"),
    "sora-2-pro-portrait-15s": ModelMetadata("sora-2-pro-portrait-15s", "sora2pro-portrait-15s"),
    "sora-2-pro-landscape-15s": ModelMetadata("sora-2-pro-landscape-15s", "sora2pro-landscape-15s"),
}

_URL_LIKE_REFERENCE_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+\-.]*://")


def get_model_metadata(external_model: str | None) -> ModelMetadata:
    model_name = (external_model or DEFAULT_EXTERNAL_MODEL).strip()
    metadata = MODEL_REGISTRY.get(model_name)
    if metadata is None:
        raise AdapterError(
            status_code=400,
            message=f"Unsupported model: {model_name}",
            error_type="invalid_request_error",
            code="unsupported_model",
        )
    return metadata


def ensure_references_supported(metadata: ModelMetadata) -> None:
    if metadata.references_supported:
        return
    raise AdapterError(
        status_code=400,
        message="references are not supported for this model",
        error_type="invalid_request_error",
        code="references_not_supported",
    )


def normalize_reference_ids(reference_ids: list[str] | None) -> list[str]:
    if reference_ids is None:
        return []
    if not isinstance(reference_ids, list):
        raise AdapterError(
            status_code=400,
            message="references must be an array of strings",
            error_type="invalid_request_error",
            code="invalid_references",
        )

    deduped: list[str] = []
    seen: set[str] = set()
    for item in reference_ids:
        if not isinstance(item, str):
            raise AdapterError(
                status_code=400,
                message="references must be an array of strings",
                error_type="invalid_request_error",
                code="invalid_references",
            )
        reference_id = item.strip()
        if not reference_id:
            raise AdapterError(
                status_code=400,
                message="references must be an array of non-empty strings",
                error_type="invalid_request_error",
                code="invalid_references",
            )
        if _URL_LIKE_REFERENCE_RE.match(reference_id):
            raise AdapterError(
                status_code=400,
                message="references must contain platform reference ids, not URLs",
                error_type="invalid_request_error",
                code="invalid_references",
            )
        if reference_id not in seen:
            seen.add(reference_id)
            deduped.append(reference_id)

    if len(deduped) > 5:
        raise AdapterError(
            status_code=400,
            message="references supports at most 5 unique ids",
            error_type="invalid_request_error",
            code="invalid_references",
        )

    return deduped


def clamp_progress(value: Any) -> int:
    try:
        progress = int(float(value))
    except (TypeError, ValueError):
        progress = 0
    return max(0, min(100, progress))


def map_task_status(status: str | None, progress: Any) -> str:
    normalized = (status or "").strip().lower()
    progress_value = clamp_progress(progress)
    if normalized == "processing":
        return "pending" if progress_value <= 0 else "processing"
    if normalized == "completed":
        return "success"
    if normalized == "failed":
        return "failed"
    return "processing"


def extract_primary_video_url(raw_value: str | None) -> str | None:
    if not raw_value:
        return None
    try:
        parsed = json.loads(raw_value)
    except json.JSONDecodeError:
        return None
    if isinstance(parsed, list) and parsed:
        first = parsed[0]
        return first if isinstance(first, str) and first else None
    return None


def extract_log_error_message(raw_value: str | None) -> str | None:
    if not raw_value:
        return None
    try:
        parsed = json.loads(raw_value)
    except json.JSONDecodeError:
        text = raw_value.strip()
        return text or None

    if isinstance(parsed, dict):
        error_message = parsed.get("error_message")
        if isinstance(error_message, str) and error_message.strip():
            return error_message.strip()
        error = parsed.get("error")
        if isinstance(error, dict):
            nested = error.get("message")
            if isinstance(nested, str) and nested.strip():
                return nested.strip()
        if isinstance(error, str) and error.strip():
            return error.strip()
    elif isinstance(parsed, str):
        return parsed.strip() or None

    return None


def _parse_datetime(raw_value: Any) -> datetime | None:
    if raw_value is None:
        return None
    if isinstance(raw_value, datetime):
        return raw_value
    if isinstance(raw_value, (int, float)):
        return datetime.fromtimestamp(raw_value, tz=timezone.utc)
    if not isinstance(raw_value, str):
        return None

    value = raw_value.strip()
    if not value:
        return None

    normalized = value.replace("Z", "+00:00")
    for candidate in (normalized, normalized.replace(" ", "T", 1)):
        try:
            return datetime.fromisoformat(candidate)
        except ValueError:
            continue
    return None


def parse_created_timestamp(raw_value: Any) -> int | None:
    parsed = _parse_datetime(raw_value)
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    else:
        parsed = parsed.astimezone(timezone.utc)
    return int(parsed.timestamp())


def parse_completed_timestamp(raw_value: Any, timezone_name: str) -> int | None:
    parsed = _parse_datetime(raw_value)
    if parsed is None:
        return None
    target_tz = ZoneInfo(timezone_name)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=target_tz)
    else:
        parsed = parsed.astimezone(target_tz)
    return int(parsed.timestamp())
