"""Launcher for the Polo adapter service."""
from __future__ import annotations

import uvicorn

from app.config import Settings
from app.main import create_app


if __name__ == "__main__":
    settings = Settings()
    app = create_app(settings=settings)
    uvicorn.run(app, host=settings.host, port=settings.port)
