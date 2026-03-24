"""Bearer authentication for the adapter."""
from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .errors import AdapterError

security = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class AuthContext:
    api_key: str
    authorization_header: str


async def require_bearer_auth(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Security(security),
) -> AuthContext:
    """Validate bearer token and return the outbound authorization header."""

    settings = request.app.state.settings
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AdapterError(
            status_code=401,
            message="Invalid API key",
            error_type="authentication_error",
            code="invalid_api_key",
        )

    token = credentials.credentials
    if token != settings.api_key:
        raise AdapterError(
            status_code=401,
            message="Invalid API key",
            error_type="authentication_error",
            code="invalid_api_key",
        )

    return AuthContext(api_key=token, authorization_header=f"Bearer {token}")
