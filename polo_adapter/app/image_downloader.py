"""Secure image downloader for remote image_url inputs."""
from __future__ import annotations

import asyncio
import base64
import ipaddress
import logging
import socket
from typing import Awaitable, Callable, Iterable
from urllib.parse import urljoin, urlparse

import httpx

from .errors import AdapterError

ResolveFunc = Callable[[str], Awaitable[list[str]]]


class ImageDownloader:
    """Download and validate public image URLs."""

    _BLOCKED_NETWORKS = (
        ipaddress.ip_network("100.64.0.0/10"),
    )

    def __init__(
        self,
        timeout_seconds: float,
        max_bytes: int,
        max_redirects: int,
        http_client: httpx.AsyncClient | None = None,
        resolver: ResolveFunc | None = None,
    ):
        self.timeout_seconds = timeout_seconds
        self.max_bytes = max_bytes
        self.max_redirects = max_redirects
        self.logger = logging.getLogger("polo_adapter.image_downloader")
        self._http_client = http_client or httpx.AsyncClient(
            follow_redirects=False,
            timeout=httpx.Timeout(timeout_seconds),
        )
        self._resolver = resolver or self._resolve_host

    async def close(self) -> None:
        await self._http_client.aclose()

    async def download_as_base64(self, image_url: str) -> str:
        target_url = image_url
        for redirect_index in range(self.max_redirects + 1):
            await self._validate_target_url(target_url)
            try:
                response = await self._http_client.get(target_url, follow_redirects=False)
            except httpx.TimeoutException as exc:
                self.logger.warning("Image download timed out for %s", target_url)
                raise AdapterError(
                    status_code=400,
                    message="image_url download timed out",
                    error_type="invalid_request_error",
                    code="image_download_timeout",
                ) from exc
            except httpx.HTTPError as exc:
                self.logger.warning("Image download failed for %s: %s", target_url, exc)
                raise AdapterError(
                    status_code=400,
                    message=f"image_url download failed: {exc}",
                    error_type="invalid_request_error",
                    code="image_download_failed",
                ) from exc

            if response.status_code in {301, 302, 303, 307, 308}:
                location = response.headers.get("location")
                await response.aclose()
                if not location:
                    raise AdapterError(
                        status_code=400,
                        message="image_url redirect missing Location header",
                        error_type="invalid_request_error",
                        code="image_download_failed",
                    )
                if redirect_index >= self.max_redirects:
                    raise AdapterError(
                        status_code=400,
                        message="image_url exceeded redirect limit",
                        error_type="invalid_request_error",
                        code="image_download_failed",
                    )
                target_url = urljoin(target_url, location)
                continue

            try:
                return await self._consume_response(response, target_url)
            finally:
                await response.aclose()

        raise AdapterError(
            status_code=400,
            message="image_url exceeded redirect limit",
            error_type="invalid_request_error",
            code="image_download_failed",
        )

    async def _consume_response(self, response: httpx.Response, target_url: str) -> str:
        if response.status_code >= 400:
            raise AdapterError(
                status_code=400,
                message=f"image_url returned HTTP {response.status_code}",
                error_type="invalid_request_error",
                code="image_download_failed",
            )

        content_type = (response.headers.get("content-type") or "").split(";", 1)[0].strip().lower()
        if not content_type.startswith("image/"):
            self.logger.warning("Rejected non-image response for %s: %s", target_url, content_type)
            raise AdapterError(
                status_code=400,
                message="image_url response must be an image",
                error_type="invalid_request_error",
                code="invalid_image_content_type",
            )

        content_length = response.headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > self.max_bytes:
                    raise AdapterError(
                        status_code=400,
                        message="image_url exceeds maximum allowed size",
                        error_type="invalid_request_error",
                        code="image_too_large",
                    )
            except ValueError:
                pass

        chunks: list[bytes] = []
        total = 0
        async for chunk in response.aiter_bytes():
            total += len(chunk)
            if total > self.max_bytes:
                raise AdapterError(
                    status_code=400,
                    message="image_url exceeds maximum allowed size",
                    error_type="invalid_request_error",
                    code="image_too_large",
                )
            chunks.append(chunk)

        if total <= 0:
            raise AdapterError(
                status_code=400,
                message="image_url download returned an empty body",
                error_type="invalid_request_error",
                code="image_download_failed",
            )

        return base64.b64encode(b"".join(chunks)).decode("ascii")

    async def _validate_target_url(self, target_url: str) -> None:
        parsed = urlparse(target_url)
        scheme = (parsed.scheme or "").lower()
        if scheme not in {"http", "https"}:
            raise AdapterError(
                status_code=400,
                message="image_url must use http or https",
                error_type="invalid_request_error",
                code="invalid_image_url",
            )
        if parsed.username or parsed.password:
            raise AdapterError(
                status_code=400,
                message="image_url must not include embedded credentials",
                error_type="invalid_request_error",
                code="invalid_image_url",
            )

        hostname = (parsed.hostname or "").strip().lower()
        if not hostname:
            raise AdapterError(
                status_code=400,
                message="image_url must include a hostname",
                error_type="invalid_request_error",
                code="invalid_image_url",
            )
        if hostname == "localhost" or hostname.endswith(".local"):
            self.logger.warning("Rejected local hostname for image_url: %s", hostname)
            raise AdapterError(
                status_code=400,
                message="image_url must resolve to a public address",
                error_type="invalid_request_error",
                code="blocked_image_host",
            )

        resolved_ips = await self._resolver(hostname)
        self._validate_resolved_ips(hostname, resolved_ips)

    async def _resolve_host(self, hostname: str) -> list[str]:
        def resolve() -> list[str]:
            infos = socket.getaddrinfo(hostname, None, proto=socket.IPPROTO_TCP)
            resolved: list[str] = []
            for info in infos:
                ip_value = info[4][0]
                if ip_value not in resolved:
                    resolved.append(ip_value)
            return resolved

        return await asyncio.to_thread(resolve)

    def _validate_resolved_ips(self, hostname: str, ip_values: Iterable[str]) -> None:
        resolved_any = False
        for value in ip_values:
            resolved_any = True
            ip_address = ipaddress.ip_address(value)
            if (
                ip_address.is_private
                or ip_address.is_loopback
                or ip_address.is_link_local
                or ip_address.is_multicast
                or ip_address.is_unspecified
                or any(ip_address in network for network in self._BLOCKED_NETWORKS)
            ):
                self.logger.warning("Rejected non-public image host %s -> %s", hostname, value)
                raise AdapterError(
                    status_code=400,
                    message="image_url must resolve to a public address",
                    error_type="invalid_request_error",
                    code="blocked_image_host",
                )
        if not resolved_any:
            raise AdapterError(
                status_code=400,
                message="image_url hostname could not be resolved",
                error_type="invalid_request_error",
                code="invalid_image_url",
            )
