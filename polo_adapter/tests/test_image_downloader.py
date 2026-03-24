from __future__ import annotations

import pytest
import httpx

from polo_adapter.app.image_downloader import ImageDownloadError, SecureImageDownloader


def build_downloader(handler, resolver=None, max_bytes=1024, max_redirects=3):
    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, follow_redirects=False)
    return SecureImageDownloader(
        timeout_seconds=1,
        max_bytes=max_bytes,
        max_redirects=max_redirects,
        client=client,
        resolver=resolver or (lambda _host, _port: ["93.184.216.34"]),
    )


@pytest.mark.asyncio
async def test_image_downloader_success():
    async def handler(request: httpx.Request):
        return httpx.Response(200, headers={"Content-Type": "image/png"}, content=b"png-bytes")

    downloader = build_downloader(handler)
    data = await downloader.download_as_base64("https://example.com/image.png")
    assert data == "cG5nLWJ5dGVz"
    await downloader.aclose()


@pytest.mark.asyncio
async def test_image_downloader_rejects_non_image():
    async def handler(request: httpx.Request):
        return httpx.Response(200, headers={"Content-Type": "text/plain"}, content=b"text")

    downloader = build_downloader(handler)
    with pytest.raises(ImageDownloadError, match="supported image content type"):
        await downloader.download("https://example.com/not-image")
    await downloader.aclose()


@pytest.mark.asyncio
async def test_image_downloader_rejects_oversize():
    async def handler(request: httpx.Request):
        return httpx.Response(200, headers={"Content-Type": "image/png"}, content=b"x" * 20)

    downloader = build_downloader(handler, max_bytes=10)
    with pytest.raises(ImageDownloadError, match="maximum allowed size"):
        await downloader.download("https://example.com/large.png")
    await downloader.aclose()


@pytest.mark.asyncio
async def test_image_downloader_rejects_private_host_before_request():
    async def handler(request: httpx.Request):
        raise AssertionError("request should not be made for private destinations")

    downloader = build_downloader(handler, resolver=lambda _host, _port: ["127.0.0.1"])
    with pytest.raises(ImageDownloadError, match="public IP address"):
        await downloader.download("https://internal.example.com/image.png")
    await downloader.aclose()


@pytest.mark.asyncio
async def test_image_downloader_rejects_redirect_to_private_host():
    async def handler(request: httpx.Request):
        if request.url.host == "example.com":
            return httpx.Response(302, headers={"Location": "https://internal.example.com/image.png"})
        raise AssertionError("redirect target should not be requested")

    downloader = build_downloader(
        handler,
        resolver=lambda host, _port: ["93.184.216.34"] if host == "example.com" else ["10.0.0.5"],
    )
    with pytest.raises(ImageDownloadError, match="public IP address"):
        await downloader.download("https://example.com/image.png")
    await downloader.aclose()
