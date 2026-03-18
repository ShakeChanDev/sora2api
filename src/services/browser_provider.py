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
class EgressProbeObservation:
    """Single probe sample for one network path."""

    ip: Optional[str] = None
    asn: Optional[str] = None
    region: Optional[str] = None
    proxy_id: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: Optional[Dict[str, Any]]) -> Optional["EgressProbeObservation"]:
        if not isinstance(payload, dict):
            return None
        return cls(
            ip=str(payload.get("ip")) if payload.get("ip") else None,
            asn=str(payload.get("asn")) if payload.get("asn") else None,
            region=str(payload.get("region")) if payload.get("region") else None,
            proxy_id=str(payload.get("proxy_id")) if payload.get("proxy_id") else None,
            raw=payload,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ip": self.ip,
            "asn": self.asn,
            "region": self.region,
            "proxy_id": self.proxy_id,
            "raw": self.raw,
        }


@dataclass
class EgressBinding:
    """Observed network binding for a page-backed auth context."""

    provider: str
    profile_id: str
    proxy_url: Optional[str]
    page_url: Optional[str]
    proxy_policy: Optional[str] = None
    browser_observation: Optional[EgressProbeObservation] = None
    server_observation: Optional[EgressProbeObservation] = None
    same_network_identity_proven: bool = False

    @property
    def status(self) -> str:
        if self.same_network_identity_proven:
            return "proven"
        if self.browser_observation and self.server_observation:
            return "mismatch"
        return "unverified"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "provider": self.provider,
            "profile_id": self.profile_id,
            "proxy_url": self.proxy_url,
            "page_url": self.page_url,
            "proxy_policy": self.proxy_policy,
            "browser_observation": self.browser_observation.to_dict() if self.browser_observation else None,
            "server_observation": self.server_observation.to_dict() if self.server_observation else None,
            "same_network_identity_proven": self.same_network_identity_proven,
            "status": self.status,
        }

    @property
    def binding_key(self) -> str:
        source = "|".join(
            [
                self.provider or "",
                self.profile_id or "",
                self.proxy_url or "",
                self.page_url or "",
                self.proxy_policy or "",
                self.browser_observation.ip if self.browser_observation and self.browser_observation.ip else "",
                self.browser_observation.asn if self.browser_observation and self.browser_observation.asn else "",
                self.server_observation.ip if self.server_observation and self.server_observation.ip else "",
                self.server_observation.asn if self.server_observation and self.server_observation.asn else "",
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

    def to_polling_context(self) -> "PollingContext":
        return PollingContext(
            access_token=self.access_token,
            cookie_header=self.cookie_header,
            user_agent=self.user_agent,
            device_id=self.device_id,
            profile_id=self.profile_id,
            egress_binding=self.egress_binding,
            expires_at=self.expires_at,
            refreshed_at=self.refreshed_at,
        )


@dataclass
class PollingContext:
    """Task-scoped auth snapshot reused by steady-state polling."""

    access_token: str
    cookie_header: str
    user_agent: str
    device_id: Optional[str]
    profile_id: str
    egress_binding: EgressBinding
    expires_at: Optional[datetime] = None
    refreshed_at: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "access_token": self.access_token,
            "cookie_header": self.cookie_header,
            "user_agent": self.user_agent,
            "device_id": self.device_id,
            "profile_id": self.profile_id,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "refreshed_at": self.refreshed_at.isoformat() if self.refreshed_at else None,
            "egress_binding": self.egress_binding.to_dict(),
        }

    @classmethod
    def from_dict(cls, payload: Optional[Dict[str, Any]]) -> Optional["PollingContext"]:
        if not isinstance(payload, dict):
            return None
        expires_at = payload.get("expires_at")
        refreshed_at = payload.get("refreshed_at")
        binding_payload = payload.get("egress_binding") or {}
        return cls(
            access_token=payload.get("access_token") or "",
            cookie_header=payload.get("cookie_header") or "",
            user_agent=payload.get("user_agent") or "",
            device_id=payload.get("device_id"),
            profile_id=payload.get("profile_id") or "",
            expires_at=datetime.fromisoformat(expires_at) if expires_at else None,
            refreshed_at=datetime.fromisoformat(refreshed_at) if refreshed_at else None,
            egress_binding=EgressBinding(
                provider=binding_payload.get("provider") or "",
                profile_id=binding_payload.get("profile_id") or "",
                proxy_url=binding_payload.get("proxy_url"),
                page_url=binding_payload.get("page_url"),
                proxy_policy=binding_payload.get("proxy_policy"),
                browser_observation=EgressProbeObservation.from_payload(binding_payload.get("browser_observation")),
                server_observation=EgressProbeObservation.from_payload(binding_payload.get("server_observation")),
                same_network_identity_proven=bool(binding_payload.get("same_network_identity_proven")),
            ),
        )


@dataclass
class MutationResult:
    """Normalized result for task-producing mutations."""

    task_id: Optional[str]
    polling_context: PollingContext
    auth_snapshot_id: str
    response_data: Dict[str, Any] = field(default_factory=dict)


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
