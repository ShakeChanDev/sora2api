"""Adapter error helpers."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse


@dataclass
class ErrorEnvelope:
    message: str
    error_type: str
    code: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "error": {
                "message": self.message,
                "type": self.error_type,
                "code": self.code,
            }
        }


class AdapterError(Exception):
    """Structured application error."""

    def __init__(self, status_code: int, message: str, error_type: str, code: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.error_type = error_type
        self.code = code

    def to_response(self) -> JSONResponse:
        return JSONResponse(
            status_code=self.status_code,
            content=ErrorEnvelope(
                message=self.message,
                error_type=self.error_type,
                code=self.code,
            ).to_dict(),
        )


async def adapter_error_handler(_: Request, exc: AdapterError) -> JSONResponse:
    return exc.to_response()


async def unhandled_error_handler(_: Request, exc: Exception) -> JSONResponse:
    return AdapterError(
        status_code=500,
        message="Internal server error",
        error_type="server_error",
        code="internal_error",
    ).to_response()
