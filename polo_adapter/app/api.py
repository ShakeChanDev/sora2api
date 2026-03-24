"""Public Polo-compatible API routes."""
from __future__ import annotations

import logging
import time

from fastapi import APIRouter, Depends, Request

from .auth import AuthContext, require_bearer_auth
from .errors import AdapterError
from .mappers import (
    clamp_progress,
    ensure_references_supported,
    extract_log_error_message,
    extract_primary_video_url,
    get_model_metadata,
    map_task_status,
    normalize_reference_ids,
    parse_timestamp,
)
from .schemas import VideoCreateRequest, VideoCreateResponse, VideoGenerationResponse

router = APIRouter()
logger = logging.getLogger("polo_adapter.api")


@router.post("/videos", response_model=VideoCreateResponse)
async def create_video(
    payload: VideoCreateRequest,
    request: Request,
    auth: AuthContext = Depends(require_bearer_auth),
) -> VideoCreateResponse:
    metadata = get_model_metadata(payload.model)
    references = normalize_reference_ids(payload.references)
    if references:
        ensure_references_supported(metadata)
        existing = await request.app.state.sqlite_repo.get_existing_reference_ids(references)
        missing = [reference_id for reference_id in references if reference_id not in existing]
        if missing:
            raise AdapterError(
                status_code=400,
                message=f"reference {missing[0]} not found",
                error_type="invalid_request_error",
                code="reference_not_found",
            )

    image_base64 = None
    if payload.image_url:
        image_base64 = await request.app.state.image_downloader.download_as_base64(payload.image_url)

    upstream_body = {
        "model": metadata.internal_name,
        "messages": [{"role": "user", "content": payload.prompt}],
        "stream": True,
    }
    if image_base64:
        upstream_body["image"] = image_base64
    if references:
        upstream_body["references"] = references
    if payload.style is not None:
        upstream_body["style"] = payload.style

    session = await request.app.state.main_service_client.create_video_session(
        authorization_header=auth.authorization_header,
        payload=upstream_body,
        request_id=request.state.request_id,
    )
    request.app.state.background_streams.start(
        name=f"drain-{session.task_id}",
        coro=session.drain(),
    )

    logger.info(
        "request_id=%s task_id=%s create_video_pending model=%s",
        request.state.request_id,
        session.task_id,
        payload.model,
    )
    return VideoCreateResponse(
        id=session.task_id,
        object="video.generation",
        created=int(time.time()),
        model=metadata.external_name,
        status="pending",
    )


@router.get("/videos/generations/{task_id}", response_model=VideoGenerationResponse)
async def get_video_generation(
    task_id: str,
    request: Request,
    _: AuthContext = Depends(require_bearer_auth),
) -> VideoGenerationResponse:
    record = await request.app.state.sqlite_repo.get_task(task_id)
    if record is None:
        raise AdapterError(
            status_code=404,
            message=f"Task {task_id} not found",
            error_type="invalid_request_error",
            code="task_not_found",
        )

    status = map_task_status(record.status, record.progress)
    error_message = record.error_message
    if not error_message and status == "failed":
        error_message = extract_log_error_message(
            await request.app.state.sqlite_repo.get_latest_request_log_response(task_id)
        )

    return VideoGenerationResponse(
        id=record.task_id,
        status=status,
        progress=clamp_progress(record.progress),
        video_url=extract_primary_video_url(record.result_urls),
        error_message=error_message,
        created_at=parse_timestamp(record.created_at),
        completed_at=parse_timestamp(record.completed_at),
    )
