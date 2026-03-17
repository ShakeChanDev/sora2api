"""Browser provider abstractions for page-bound mutations."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from hashlib import sha256
from typing import Any, Dict, Optional


def stable_hash(value: Optional[str]) -> Optional[str]:
    """Return a stable sha256 hash for an in-memory secret."""
    if not value:
        return None
    return sha256(value.encode("utf-8")).hexdigest()


class BrowserProviderError(RuntimeError):
    """Base browser provider error."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class BrowserReadinessError(BrowserProviderError):
    """Raised when a profile/page is not ready for execution."""


class BrowserAuthError(BrowserProviderError):
    """Raised when page auth refresh fails."""


class BrowserMutationError(BrowserProviderError):
    """Raised when page mutation execution fails."""


@dataclass
class EgressBinding:
    """Observed network binding for a page-backed auth context."""

    provider: str
    profile_id: str
    proxy_url: Optional[str]
    page_url: Optional[str]
    same_network_identity_proven: bool = False

    @property
    def binding_key(self) -> str:
        source = "|".join(
            [
                self.provider or "",
                self.profile_id or "",
                self.proxy_url or "",
                self.page_url or "",
                "1" if self.same_network_identity_proven else "0",
            ]
        )
        return sha256(source.encode("utf-8")).hexdigest()


@dataclass
class AuthContext:
    """Fresh page-side auth context used for high-risk mutations."""

    access_token: str
    cookie_header: str
    user_agent: str
    device_id: Optional[str]
    sentinel_token: str
    refreshed_at: datetime
    provider: str
    profile_id: str
    page_url: str
    egress_binding: EgressBinding
    expires_at: Optional[datetime] = None
    session_payload: Dict[str, Any] = field(default_factory=dict)

    @property
    def cookie_jar_hash(self) -> Optional[str]:
        return stable_hash(self.cookie_header)

    @property
    def user_agent_hash(self) -> Optional[str]:
        return stable_hash(self.user_agent)

    @property
    def auth_context_hash(self) -> str:
        parts = [
            self.access_token,
            self.cookie_header,
            self.user_agent,
            self.device_id or "",
            self.page_url,
            self.egress_binding.binding_key,
        ]
        return sha256("|".join(parts).encode("utf-8")).hexdigest()


@dataclass
class BrowserConnection:
    """Opaque provider connection with an attached page."""

    provider: str
    profile_id: str
    debugger_url: str
    proxy_url: Optional[str]
    browser: Any
    context: Any
    page: Any
    page_id: Optional[str]
    playwright: Any = None


@dataclass
class BrowserPageContext:
    """Page metadata needed for locking and observability."""

    profile_id: str
    page_id: Optional[str]
    page_url: str
    title: Optional[str]
    provider: str


@dataclass
class BrowserMutationRequest:
    """Single in-page fetch request."""

    method: str
    url: str
    json_body: Optional[Dict[str, Any]] = None
    headers: Dict[str, str] = field(default_factory=dict)
    expected_status: Optional[int] = None


@dataclass
class BrowserMutationResponse:
    """Normalized result of an in-page fetch request."""

    status: int
    ok: bool
    headers: Dict[str, str]
    data: Optional[Dict[str, Any]]
    text: str
    page_url: str


class BrowserProvider(ABC):
    """Abstract browser provider."""

    provider_name: str

    @abstractmethod
    async def start(self, profile_id: str) -> Dict[str, Any]:
        """Start a browser profile if it is not running."""

    @abstractmethod
    async def stop(self, profile_id: str) -> Dict[str, Any]:
        """Stop a browser profile."""

    @abstractmethod
    async def connect_profile(self, profile_id: str, preferred_url: Optional[str] = None) -> BrowserConnection:
        """Connect to a running profile and resolve a page."""

    @abstractmethod
    async def readiness_check(self, connection: BrowserConnection, preferred_url: Optional[str] = None) -> BrowserPageContext:
        """Ensure the page is reachable, on the right origin, and not challenged."""

    @abstractmethod
    async def get_page_context(self, connection: BrowserConnection) -> BrowserPageContext:
        """Return page metadata without refreshing auth state."""

    @abstractmethod
    async def refresh_auth_context(
        self,
        connection: BrowserConnection,
        flow: str,
        preferred_url: Optional[str] = None,
    ) -> AuthContext:
        """Refresh page auth context and collect browser-bound credentials."""

    @abstractmethod
    async def fetch_json(
        self,
        connection: BrowserConnection,
        request: BrowserMutationRequest,
        auth_context: AuthContext,
    ) -> BrowserMutationResponse:
        """Execute a same-origin fetch inside the page context."""

    @abstractmethod
    async def execute_in_page(self, connection: BrowserConnection, script: str, arg: Optional[dict] = None) -> Any:
        """Execute arbitrary JavaScript in the page context."""

    @abstractmethod
    async def recover_same_profile(self, profile_id: str, preferred_url: Optional[str] = None) -> BrowserConnection:
        """Reconnect to the same profile after a page/browser failure."""

    @abstractmethod
    async def disconnect(self, connection: BrowserConnection):
        """Release the provider connection without destroying the profile."""
