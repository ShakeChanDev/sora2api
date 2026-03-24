"""FastAPI app factory for the Polo adapter."""
from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError

from .api import router
from .background_streams import BackgroundStreamDrainer
from .config import Settings
from .errors import AdapterError, adapter_error_handler, unhandled_error_handler
from .image_downloader import ImageDownloader
from .main_service_client import MainServiceClient
from .sqlite_repo import SQLiteReadRepository


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def create_app(
    *,
    settings: Settings | None = None,
    main_service_client: MainServiceClient | None = None,
    sqlite_repo: SQLiteReadRepository | None = None,
    image_downloader: ImageDownloader | None = None,
    background_streams: BackgroundStreamDrainer | None = None,
) -> FastAPI:
    configure_logging()
    resolved_settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = resolved_settings
        app.state.main_service_client = main_service_client or MainServiceClient(
            base_url=resolved_settings.main_base_url,
            task_id_wait_seconds=resolved_settings.task_id_wait_seconds,
            connect_timeout_seconds=resolved_settings.main_connect_timeout_seconds,
        )
        app.state.sqlite_repo = sqlite_repo or SQLiteReadRepository(
            db_path=resolved_settings.sqlite_path,
            busy_timeout_ms=resolved_settings.sqlite_busy_timeout_ms,
        )
        app.state.image_downloader = image_downloader or ImageDownloader(
            timeout_seconds=resolved_settings.image_timeout_seconds,
            max_bytes=resolved_settings.image_max_bytes,
            max_redirects=resolved_settings.image_max_redirects,
        )
        app.state.background_streams = background_streams or BackgroundStreamDrainer()
        try:
            yield
        finally:
            await app.state.background_streams.close()
            await app.state.main_service_client.close()
            await app.state.image_downloader.close()
            await app.state.sqlite_repo.close()

    app = FastAPI(
        title="Polo Adapter",
        version="1.0.0",
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        request.state.request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        response = await call_next(request)
        response.headers["x-request-id"] = request.state.request_id
        return response

    @app.exception_handler(AdapterError)
    async def adapter_exception_handler(request: Request, exc: AdapterError):
        return await adapter_error_handler(request, exc)

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(_: Request, exc: RequestValidationError):
        first_error = exc.errors()[0] if exc.errors() else {}
        message = first_error.get("msg") or "Invalid request body"
        return AdapterError(
            status_code=400,
            message=message,
            error_type="invalid_request_error",
            code="invalid_request",
        ).to_response()

    @app.exception_handler(Exception)
    async def generic_exception_handler(request: Request, exc: Exception):
        logging.getLogger("polo_adapter.app").exception(
            "request_id=%s unhandled_error=%s",
            getattr(request.state, "request_id", "unknown"),
            exc,
        )
        return await unhandled_error_handler(request, exc)

    @app.get("/healthz")
    async def healthz() -> dict[str, Any]:
        return {"status": "ok"}

    app.include_router(router)
    return app
