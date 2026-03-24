"""Map main-service task rows into Polo-compatible responses."""
from __future__ import annotations

import json
from typing import Optional

from .schemas import RequestLogRecord, TaskRecord, VideoStatusResponse
from .time_utils import sqlite_local_to_unix, sqlite_utc_to_unix


def normalize_progress(progress: float) -> float:
    """Clamp progress to the public 0-100 range."""

    return max(0.0, min(100.0, float(progress or 0.0)))


def map_task_status(status: str, progress: float) -> str:
    """Map main-service task status into Polo-compatible states."""

    normalized_progress = normalize_progress(progress)
    if status == "processing":
        return "pending" if normalized_progress <= 0 else "processing"
    if status == "completed":
        return "success"
    if status == "failed":
        return "failed"
    return "processing"


def extract_video_url(result_urls: Optional[str]) -> Optional[str]:
    """Extract the first video url from a JSON-encoded result_urls array."""

    if not result_urls:
        return None
    try:
        parsed = json.loads(result_urls)
    except Exception:
        return None
    if not isinstance(parsed, list) or not parsed:
        return None
    first = parsed[0]
    return first if isinstance(first, str) else None


def extract_error_message(task: TaskRecord, request_log: Optional[RequestLogRecord]) -> Optional[str]:
    """Prefer task.error_message, then fallback to request_logs.response_body diagnostics."""

    if task.error_message:
        return task.error_message
    if request_log is None or not request_log.response_body:
        return None

    try:
        payload = json.loads(request_log.response_body)
    except Exception:
        return request_log.response_body

    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            message = error.get("message")
            if isinstance(message, str) and message.strip():
                return message.strip()
        if isinstance(error, str) and error.strip():
            return error.strip()
        error_message = payload.get("error_message")
        if isinstance(error_message, str) and error_message.strip():
            return error_message.strip()
    return None


def build_status_response(
    task: TaskRecord,
    request_log: Optional[RequestLogRecord],
    main_local_tz: str,
) -> VideoStatusResponse:
    """Build a public task status response."""

    return VideoStatusResponse(
        id=task.task_id,
        status=map_task_status(task.status, task.progress),
        progress=normalize_progress(task.progress),
        video_url=extract_video_url(task.result_urls),
        error_message=extract_error_message(task, request_log),
        created_at=sqlite_utc_to_unix(task.created_at),
        completed_at=sqlite_local_to_unix(task.completed_at, main_local_tz),
    )
