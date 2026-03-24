"""HTTP client for the main Sora2Api service."""
from __future__ import annotations

from dataclasses import dataclass

import httpx


class MainServiceError(RuntimeError):
    """Raised when the main service create endpoint cannot be used."""

    def __init__(self, message: str, status_code: int | None = None, body: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


@dataclass(slots=True)
class MainServiceStream:
    """Open SSE response stream from the main service."""

    response: httpx.Response
    _context_manager: object

    async def aiter_lines(self):
        async for line in self.response.aiter_lines():
            yield line

    async def read_text(self) -> str:
        data = await self.response.aread()
        return data.decode("utf-8", errors="replace")

    async def aclose(self) -> None:
        await self._context_manager.__aexit__(None, None, None)


class MainServiceClient:
    """Client for POST /v1/chat/completions on the main service."""

    def __init__(self, base_url: str, client: httpx.AsyncClient | None = None):
        self.base_url = base_url.rstrip("/")
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10.0, write=10.0, read=None, pool=10.0),
            headers={"Accept": "text/event-stream"},
        )

    async def aclose(self) -> None:
        """Close the shared HTTP client if owned by this instance."""

        if self._owns_client:
            await self._client.aclose()

    async def start_create_stream(self, payload: dict, bearer: str) -> MainServiceStream:
        """Open the main service create stream and validate the upstream response."""

        context_manager = self._client.stream(
            "POST",
            f"{self.base_url}/v1/chat/completions",
            headers={"Authorization": f"Bearer {bearer}"},
            json=payload,
        )
        response = await context_manager.__aenter__()

        if response.status_code != 200:
            body = await response.aread()
            text = body.decode("utf-8", errors="replace")
            await context_manager.__aexit__(None, None, None)
            raise MainServiceError(
                f"main service returned HTTP {response.status_code}",
                status_code=response.status_code,
                body=text,
            )

        content_type = response.headers.get("content-type", "")
        if "text/event-stream" not in content_type.lower():
            body = await response.aread()
            text = body.decode("utf-8", errors="replace")
            await context_manager.__aexit__(None, None, None)
            raise MainServiceError(
                "main service did not return text/event-stream",
                status_code=response.status_code,
                body=text,
            )

        return MainServiceStream(response=response, _context_manager=context_manager)
