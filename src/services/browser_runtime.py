"""Browser runtime abstractions for page-backed auth refresh and mutations."""
import asyncio
import json
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, AsyncIterator, Dict, List, Optional

from ..core.logger import debug_logger


AUTH_ERROR_CODES = {
    "AUTH_CONTEXT_INCOMPLETE": "auth_context_incomplete",
    "AUTH_CONTEXT_INVALID": "auth_context_invalid",
    "SENTINEL_NOT_READY": "sentinel_not_ready",
    "CLOUDFLARE_CHALLENGE": "cloudflare_challenge",
    "TARGET_CLOSED": "TARGET_CLOSED",
    "ECONNREFUSED": "ECONNREFUSED",
    "EXECUTION_CONTEXT_DESTROYED": "execution_context_destroyed",
    "PROFILE_LOCKED_TIMEOUT": "profile_locked_timeout",
    "WINDOW_LOCKED_TIMEOUT": "window_locked_timeout",
}


@dataclass
class BrowserHandle:
    provider: str
    profile_id: str
    profile_path: str
    window_id: str
    connected_at: datetime
    state: str
    browser: Any = None
    page: Any = None
    context: Any = None
    driver: Any = None


@dataclass
class BrowserReadiness:
    ready: bool
    page_url: Optional[str] = None
    challenge_detected: bool = False
    sentinel_ready: bool = False
    message: Optional[str] = None


@dataclass
class PageContext:
    page_url: str
    user_agent: str
    cookie_header: str
    device_id: Optional[str]
    session_fetched_at: datetime


@dataclass
class AuthContext:
    access_token: str
    cookie_header: str
    user_agent: str
    device_id: Optional[str]
    sentinel_token: Optional[str]
    sentinel_ready: bool
    source: str
    refreshed_at: datetime


@dataclass
class MutationAttempt:
    strategy: str
    success: bool
    error_code: Optional[str] = None
    upstream_status: Optional[int] = None
    message: Optional[str] = None


@dataclass
class MutationExecutionContext:
    task_id: Optional[str]
    token_id: int
    profile_id: str
    mutation_type: str
    strategy: str
    auth_context: AuthContext
    phase: str
    window_id: Optional[str] = None
    attempts: List[MutationAttempt] = field(default_factory=list)


@dataclass
class MutationExecutionResult:
    task_id: Optional[str]
    raw_result: Any
    strategy: str
    attempts: List[MutationAttempt]
    auth_context: AuthContext
    profile_id: str
    window_id: Optional[str]


class BrowserAuthError(Exception):
    """Structured browser/auth refresh error."""

    def __init__(self, code: str, message: str, *, upstream_status: Optional[int] = None):
        super().__init__(message)
        self.code = code
        self.upstream_status = upstream_status


class UpstreamExecutionError(Exception):
    """Structured upstream execution error."""

    def __init__(
        self,
        message: str,
        *,
        status_code: Optional[int] = None,
        error_code: Optional[str] = None,
        response_body: Any = None,
        high_risk: bool = False,
    ):
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        self.response_body = response_body
        self.high_risk = high_risk


def classify_high_risk_failure(error: Exception) -> bool:
    """Decide whether a failure should trigger page fallback."""
    if isinstance(error, BrowserAuthError):
        return True

    if isinstance(error, UpstreamExecutionError):
        if error.high_risk:
            return True
        if error.status_code in {401, 403}:
            return True
        lowered = f"{error.error_code or ''} {error}".lower()
    else:
        lowered = str(error).lower()

    return any(
        token in lowered
        for token in (
            "challenge",
            "cloudflare",
            "sentinel",
            "auth",
            "device",
            "session",
            "invalid_request",
            "unable to process request",
            "forbidden",
            "timeout",
            "timed out",
            "curl: (28)",
            "connection refused",
            "econnrefused",
            "401",
            "403",
        )
    )


class NamedAsyncLockManager:
    """Per-key asyncio lock manager with timeout support."""

    def __init__(self):
        self._locks: Dict[str, asyncio.Lock] = {}
        self._registry_lock = asyncio.Lock()

    async def _get_lock(self, name: str) -> asyncio.Lock:
        async with self._registry_lock:
            if name not in self._locks:
                self._locks[name] = asyncio.Lock()
            return self._locks[name]

    @asynccontextmanager
    async def acquire(self, name: str, timeout: float, timeout_code: str) -> AsyncIterator[None]:
        lock = await self._get_lock(name)
        try:
            await asyncio.wait_for(lock.acquire(), timeout=timeout)
        except asyncio.TimeoutError as exc:
            raise BrowserAuthError(timeout_code, f"Timed out waiting for lock: {name}") from exc
        try:
            yield
        finally:
            if lock.locked():
                lock.release()


class BrowserLockManager:
    """Two-level lock manager for profile and window coordination."""

    def __init__(self):
        self._profile_locks = NamedAsyncLockManager()
        self._window_locks = NamedAsyncLockManager()
        self._startup_queue = asyncio.Lock()

    @asynccontextmanager
    async def profile_lock(self, profile_id: str, timeout: float = 30.0) -> AsyncIterator[None]:
        async with self._profile_locks.acquire(
            profile_id, timeout, AUTH_ERROR_CODES["PROFILE_LOCKED_TIMEOUT"]
        ):
            yield

    @asynccontextmanager
    async def window_lock(self, window_id: str, timeout: float = 30.0) -> AsyncIterator[None]:
        async with self._window_locks.acquire(
            window_id, timeout, AUTH_ERROR_CODES["WINDOW_LOCKED_TIMEOUT"]
        ):
            yield

    @asynccontextmanager
    async def startup_lock(self) -> AsyncIterator[None]:
        async with self._startup_queue:
            yield


def extract_upstream_error(response: Dict[str, Any], fallback_message: str) -> UpstreamExecutionError:
    """Convert a JSON fetch response into a structured error."""
    status = response.get("status")
    payload = response.get("json")
    error_code = None
    message = fallback_message

    if isinstance(payload, dict):
        error_info = payload.get("error")
        if isinstance(error_info, dict):
            error_code = error_info.get("code")
            message = error_info.get("message") or message

    lowered_message = (message or "").lower()
    high_risk = status in {401, 403}
    if status == 400 and error_code == "invalid_request":
        high_risk = True
    if "unable to process request" in lowered_message:
        high_risk = True
    return UpstreamExecutionError(
        message,
        status_code=status,
        error_code=error_code,
        response_body=payload or response.get("text"),
        high_risk=high_risk,
    )


def safe_json_dumps(value: Any) -> str:
    """Best-effort JSON encoding for logging or DB storage."""
    return json.dumps(value, ensure_ascii=False, default=str)


def append_attempt(
    attempts: List[MutationAttempt],
    strategy: str,
    success: bool,
    *,
    error_code: Optional[str] = None,
    upstream_status: Optional[int] = None,
    message: Optional[str] = None,
) -> None:
    attempts.append(
        MutationAttempt(
            strategy=strategy,
            success=success,
            error_code=error_code,
            upstream_status=upstream_status,
            message=message,
        )
    )
    debug_logger.log_info(
        f"[Mutation] strategy={strategy} success={success} "
        f"error_code={error_code or '-'} upstream_status={upstream_status or '-'}"
    )
