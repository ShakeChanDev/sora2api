"""FastAPI app factory and entrypoint for the Polo adapter service."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError

from .api import AdapterServices, router, validation_exception_handler
from .image_downloader import SecureImageDownloader
from .main_service_client import MainServiceClient
from .settings import Settings
from .sqlite_repo import SQLiteReadRepository

logging.basicConfig(level=logging.INFO)


def build_services(settings: Settings) -> AdapterServices:
    """Build the default service container."""

    return AdapterServices(
        settings=settings,
        repo=SQLiteReadRepository(settings.db_path),
        image_downloader=SecureImageDownloader(
            timeout_seconds=settings.image_download_timeout_seconds,
            max_bytes=settings.image_max_bytes,
            max_redirects=settings.image_max_redirects,
        ),
        main_service_client=MainServiceClient(settings.main_base_url),
    )


def create_app(
    settings: Settings | None = None,
    services: AdapterServices | None = None,
) -> FastAPI:
    """Create a configured FastAPI app."""

    resolved_settings = settings or Settings()
    resolved_services = services or build_services(resolved_settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await resolved_services.repo.validate_shared_api_key(resolved_settings.shared_api_key)
        app.state.services = resolved_services
        try:
            yield
        finally:
            if hasattr(resolved_services.image_downloader, "aclose"):
                await resolved_services.image_downloader.aclose()
            if hasattr(resolved_services.main_service_client, "aclose"):
                await resolved_services.main_service_client.aclose()

    app = FastAPI(
        title="Polo Adapter",
        version="1.0.0",
        lifespan=lifespan,
    )
    app.include_router(router)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    return app


app = create_app()


def main() -> None:
    """Run the adapter service with uvicorn."""

    settings = Settings()
    uvicorn.run(
        "polo_adapter.app.main:app",
        host=settings.adapter_host,
        port=settings.adapter_port,
        reload=False,
    )


if __name__ == "__main__":
    main()
