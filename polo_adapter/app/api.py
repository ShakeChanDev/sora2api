"""FastAPI routes for the Polo-compatible adapter service."""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .auth import verify_bearer_header
from .image_downloader import ImageDownloadError
from .main_service_client import MainServiceClient, MainServiceError
from .model_mapping import DEFAULT_PUBLIC_MODEL, resolve_model
from .schemas import VideoCreateRequest, VideoCreateResponse
from .sse_worker import MainServiceSSEWorker, SSEProtocolError
from .status_mapper import build_status_response

logger = logging.getLogger(__name__)
router = APIRouter()


@dataclass(slots=True)
class AdapterServices:
    """Runtime services stored in FastAPI app state."""

    settings: Any
    repo: Any
    image_downloader: Any
    main_service_client: MainServiceClient


def get_services(request: Request) -> AdapterServices:
    """Return the adapter services container from FastAPI app state."""

    return request.app.state.services


async def require_bearer(
    request: Request,
    services: AdapterServices = Depends(get_services),
) -> str:
    """Validate and return the shared API key bearer token."""

    return verify_bearer_header(request, services.settings.shared_api_key)


@router.post("/videos", response_model=VideoCreateResponse)
async def create_video(
    payload: VideoCreateRequest,
    bearer: str = Depends(require_bearer),
    services: AdapterServices = Depends(get_services),
) -> VideoCreateResponse:
    """Create a Polo-compatible video task through the main service."""

    try:
        model_mapping = resolve_model(payload.model)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"unsupported model: {payload.model}") from exc

    normalized_references = _normalize_references(payload.references)
    if normalized_references and not model_mapping.supports_references:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="references are only supported for standard video and storyboard generation",
        )

    if normalized_references:
        existing_ids = await services.repo.get_reference_ids(normalized_references)
        missing_ids = [reference_id for reference_id in normalized_references if reference_id not in existing_ids]
        if missing_ids:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"reference {missing_ids[0]} not found",
            )

    image_base64 = None
    if payload.image_url:
        try:
            image_base64 = await services.image_downloader.download_as_base64(payload.image_url)
        except ImageDownloadError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    main_request_body: dict[str, Any] = {
        "model": model_mapping.main_service_name,
        "messages": [{"role": "user", "content": payload.prompt}],
        "stream": True,
    }
    if image_base64 is not None:
        main_request_body["image"] = image_base64
    if normalized_references:
        main_request_body["references"] = normalized_references
    if payload.style is not None:
        main_request_body["style"] = payload.style

    try:
        stream = await services.main_service_client.start_create_stream(main_request_body, bearer)
        worker = MainServiceSSEWorker(stream)
        await worker.start()
        task_id = await worker.wait_for_task_id(services.settings.create_timeout_seconds)
    except asyncio.TimeoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="timed out waiting for main service task_id",
        ) from exc
    except (MainServiceError, SSEProtocolError) as exc:
        logger.warning("POST /videos upstream failure: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        logger.exception("Unexpected POST /videos failure")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"unexpected upstream failure: {exc}",
        ) from exc

    return VideoCreateResponse(
        id=task_id,
        created=int(time.time()),
        model=payload.model or DEFAULT_PUBLIC_MODEL,
        status="pending",
    )


@router.get("/videos/generations/{task_id}")
async def get_video_generation(
    task_id: str,
    _: str = Depends(require_bearer),
    services: AdapterServices = Depends(get_services),
):
    """Query a task status from the shared SQLite database."""

    task = await services.repo.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="task not found")

    request_log = await services.repo.get_latest_request_log(task_id)
    return build_status_response(task, request_log, services.settings.main_local_tz)


async def validation_exception_handler(_: Request, exc: RequestValidationError):
    """Map request validation errors to 400 parameter errors."""

    detail = exc.errors()[0].get("msg", "invalid request")
    if isinstance(detail, str) and detail.startswith("Value error, "):
        detail = detail[len("Value error, ") :]
    return JSONResponse(status_code=status.HTTP_400_BAD_REQUEST, content={"detail": detail})


def _normalize_references(references: list[str] | None) -> list[str]:
    if references is None:
        return []

    deduped: list[str] = []
    seen: set[str] = set()
    for item in references:
        reference_id = item.strip()
        if not reference_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="references must be an array of strings",
            )
        if reference_id not in seen:
            seen.add(reference_id)
            deduped.append(reference_id)

    if len(deduped) > 5:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="references supports at most 5 unique ids",
        )

    return deduped
