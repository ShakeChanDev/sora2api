"""Secure remote image download and base64 conversion."""
from __future__ import annotations

import base64
import ipaddress
import socket
from typing import Callable, Iterable
from urllib.parse import urljoin, urlparse

import httpx


class ImageDownloadError(ValueError):
    """Raised when a remote image download fails validation."""


class SecureImageDownloader:
    """Download remote images with SSRF protections and size/content validation."""

    def __init__(
        self,
        timeout_seconds: float,
        max_bytes: int,
        max_redirects: int,
        client: httpx.AsyncClient | None = None,
        resolver: Callable[[str, int], Iterable[str]] | None = None,
    ):
        self.timeout_seconds = timeout_seconds
        self.max_bytes = max_bytes
        self.max_redirects = max_redirects
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_seconds, connect=timeout_seconds),
            follow_redirects=False,
            headers={
                "User-Agent": "polo-adapter/1.0",
                "Accept": "image/*,*/*;q=0.1",
            },
        )
        self._resolver = resolver or self._default_resolver

    async def aclose(self) -> None:
        """Close the internal HTTP client if owned by this instance."""

        if self._owns_client:
            await self._client.aclose()

    async def download_as_base64(self, url: str) -> str:
        """Download a remote image and return a bare base64 string."""

        content = await self.download(url)
        return base64.b64encode(content).decode("ascii")

    async def download(self, url: str) -> bytes:
        """Download and validate a public image URL."""

        current_url = self._normalize_url(url)
        for redirect_count in range(self.max_redirects + 1):
            self._validate_public_destination(current_url)
            async with self._client.stream("GET", current_url) as response:
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location")
                    if not location:
                        raise ImageDownloadError("image_url redirect response is missing Location header")
                    if redirect_count >= self.max_redirects:
                        raise ImageDownloadError("image_url exceeded the maximum redirect count")
                    current_url = self._normalize_url(urljoin(current_url, location))
                    continue

                if response.status_code >= 400:
                    raise ImageDownloadError(f"image_url download failed with HTTP {response.status_code}")

                content_type = response.headers.get("Content-Type", "")
                self._validate_content_type(content_type)

                content_length = response.headers.get("Content-Length")
                if content_length:
                    try:
                        if int(content_length) > self.max_bytes:
                            raise ImageDownloadError("image_url exceeds the maximum allowed size")
                    except ValueError:
                        pass

                chunks = bytearray()
                async for chunk in response.aiter_bytes():
                    chunks.extend(chunk)
                    if len(chunks) > self.max_bytes:
                        raise ImageDownloadError("image_url exceeds the maximum allowed size")
                return bytes(chunks)

        raise ImageDownloadError("image_url exceeded the maximum redirect count")

    def _normalize_url(self, raw_url: str) -> str:
        parsed = urlparse(raw_url)
        if parsed.scheme not in {"http", "https"}:
            raise ImageDownloadError("image_url must use http or https")
        if not parsed.hostname:
            raise ImageDownloadError("image_url must include a hostname")
        return parsed.geturl()

    def _validate_content_type(self, content_type: str) -> None:
        normalized = content_type.split(";", 1)[0].strip().lower()
        if not normalized.startswith("image/") or normalized == "image/svg+xml":
            raise ImageDownloadError("image_url response must be a supported image content type")

    def _validate_public_destination(self, url: str) -> None:
        parsed = urlparse(url)
        hostname = parsed.hostname or ""
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        try:
            ip_obj = ipaddress.ip_address(hostname)
            if not ip_obj.is_global:
                raise ImageDownloadError("image_url target must resolve to a public IP address")
            return
        except ValueError:
            pass

        resolved_ips = list(self._resolver(hostname, port))
        if not resolved_ips:
            raise ImageDownloadError("image_url hostname could not be resolved")
        for ip_text in resolved_ips:
            ip_obj = ipaddress.ip_address(ip_text)
            if not ip_obj.is_global:
                raise ImageDownloadError("image_url target must resolve to a public IP address")

    @staticmethod
    def _default_resolver(hostname: str, port: int) -> Iterable[str]:
        infos = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
        seen: set[str] = set()
        for family, _, _, _, sockaddr in infos:
            if family not in {socket.AF_INET, socket.AF_INET6}:
                continue
            ip_text = sockaddr[0]
            if ip_text not in seen:
                seen.add(ip_text)
                yield ip_text
