import unittest

import httpx

from polo_adapter.app.errors import AdapterError
from polo_adapter.app.image_downloader import ImageDownloader


class ImageDownloaderTests(unittest.IsolatedAsyncioTestCase):
    async def test_downloads_public_image_as_base64(self):
        resolved_hosts = []

        async def resolver(hostname: str):
            resolved_hosts.append(hostname)
            return ["93.184.216.34"]

        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                headers={"content-type": "image/png", "content-length": "4"},
                content=b"test",
            )

        downloader = ImageDownloader(
            timeout_seconds=1,
            max_bytes=1024,
            max_redirects=2,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
            resolver=resolver,
        )

        payload = await downloader.download_as_base64("https://example.com/image.png")

        self.assertEqual(payload, "dGVzdA==")
        self.assertEqual(resolved_hosts, ["example.com"])
        await downloader.close()

    async def test_rejects_non_image_content_type(self):
        async def resolver(_hostname: str):
            return ["93.184.216.34"]

        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, headers={"content-type": "text/plain"}, content=b"hello")

        downloader = ImageDownloader(
            timeout_seconds=1,
            max_bytes=1024,
            max_redirects=2,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
            resolver=resolver,
        )

        with self.assertRaises(AdapterError) as ctx:
            await downloader.download_as_base64("https://example.com/file.txt")

        self.assertEqual(ctx.exception.code, "invalid_image_content_type")
        await downloader.close()

    async def test_rejects_svg_images(self):
        async def resolver(_hostname: str):
            return ["93.184.216.34"]

        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, headers={"content-type": "image/svg+xml"}, content=b"<svg></svg>")

        downloader = ImageDownloader(
            timeout_seconds=1,
            max_bytes=1024,
            max_redirects=2,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
            resolver=resolver,
        )

        with self.assertRaises(AdapterError) as ctx:
            await downloader.download_as_base64("https://example.com/image.svg")

        self.assertEqual(ctx.exception.code, "invalid_image_content_type")
        await downloader.close()

    async def test_rejects_timeout(self):
        async def resolver(_hostname: str):
            return ["93.184.216.34"]

        def handler(_request: httpx.Request):
            raise httpx.ReadTimeout("timed out")

        downloader = ImageDownloader(
            timeout_seconds=1,
            max_bytes=1024,
            max_redirects=2,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
            resolver=resolver,
        )

        with self.assertRaises(AdapterError) as ctx:
            await downloader.download_as_base64("https://example.com/image.png")

        self.assertEqual(ctx.exception.code, "image_download_timeout")
        await downloader.close()

    async def test_rejects_large_images(self):
        async def resolver(_hostname: str):
            return ["93.184.216.34"]

        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                headers={"content-type": "image/png", "content-length": "2048"},
                content=b"a" * 2048,
            )

        downloader = ImageDownloader(
            timeout_seconds=1,
            max_bytes=1024,
            max_redirects=2,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
            resolver=resolver,
        )

        with self.assertRaises(AdapterError) as ctx:
            await downloader.download_as_base64("https://example.com/image.png")

        self.assertEqual(ctx.exception.code, "image_too_large")
        await downloader.close()

    async def test_rejects_private_addresses(self):
        async def resolver(_hostname: str):
            return ["127.0.0.1"]

        downloader = ImageDownloader(
            timeout_seconds=1,
            max_bytes=1024,
            max_redirects=2,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(lambda _: None)),
            resolver=resolver,
        )

        with self.assertRaises(AdapterError) as ctx:
            await downloader.download_as_base64("https://private.example/image.png")

        self.assertEqual(ctx.exception.code, "blocked_image_host")
        await downloader.close()

    async def test_revalidates_redirect_targets(self):
        resolved_hosts = []

        async def resolver(hostname: str):
            resolved_hosts.append(hostname)
            return ["93.184.216.34"]

        def handler(request: httpx.Request) -> httpx.Response:
            if str(request.url) == "https://example.com/image.png":
                return httpx.Response(302, headers={"location": "https://cdn.example.com/final.png"})
            return httpx.Response(
                200,
                headers={"content-type": "image/png", "content-length": "4"},
                content=b"done",
            )

        downloader = ImageDownloader(
            timeout_seconds=1,
            max_bytes=1024,
            max_redirects=2,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
            resolver=resolver,
        )

        payload = await downloader.download_as_base64("https://example.com/image.png")

        self.assertEqual(payload, "ZG9uZQ==")
        self.assertEqual(resolved_hosts, ["example.com", "cdn.example.com"])
        await downloader.close()


if __name__ == "__main__":
    unittest.main()
