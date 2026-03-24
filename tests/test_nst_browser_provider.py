"""Tests for NST browser provider start path selection."""
import asyncio
import copy
import unittest

from src.core.config import config
from src.services.browser_provider import BrowserProviderError
from src.services.nst_browser_provider import NSTBrowserProvider


class _FakeNSTBrowserProvider(NSTBrowserProvider):
    def __init__(self, responses):
        super().__init__(base_url="http://127.0.0.1:8848/api/v2", api_key="")
        self.responses = list(responses)
        self.calls = []

    async def _request(self, method, path, json_data=None):
        self.calls.append((method, path))
        if not self.responses:
            raise AssertionError(f"unexpected request: {(method, path)}")
        expected_method, expected_path, result = self.responses.pop(0)
        if (method, path) != (expected_method, expected_path):
            raise AssertionError(f"expected {(expected_method, expected_path)} got {(method, path)}")
        if isinstance(result, Exception):
            raise result
        return result


class NSTBrowserProviderTests(unittest.TestCase):
    def setUp(self):
        self._nst_browser_config = copy.deepcopy(config._config.get("nst_browser", {}))

    def tearDown(self):
        config._config["nst_browser"] = self._nst_browser_config

    def test_start_prefers_plain_browsers_endpoint(self):
        async def scenario():
            provider = _FakeNSTBrowserProvider([
                ("GET", "/browsers/profile-1/debugger", BrowserProviderError("browser_provider_http_error", "not running")),
                ("POST", "/browsers/profile-1", {"profileId": "profile-1"}),
                ("GET", "/browsers/profile-1/debugger", {"webSocketDebuggerUrl": "ws://debugger"}),
            ])
            result = await provider.start("profile-1")
            self.assertEqual(result["webSocketDebuggerUrl"], "ws://debugger")
            self.assertEqual(
                provider.calls,
                [
                    ("GET", "/browsers/profile-1/debugger"),
                    ("POST", "/browsers/profile-1"),
                    ("GET", "/browsers/profile-1/debugger"),
                ],
            )

        asyncio.run(scenario())

    def test_start_falls_back_to_legacy_start_endpoint(self):
        async def scenario():
            provider = _FakeNSTBrowserProvider([
                ("GET", "/browsers/profile-2/debugger", BrowserProviderError("browser_provider_http_error", "not running")),
                ("POST", "/browsers/profile-2", BrowserProviderError("browser_provider_http_error", "404")),
                ("POST", "/browsers/profile-2/start", {"profileId": "profile-2"}),
                ("GET", "/browsers/profile-2/debugger", {"webSocketDebuggerUrl": "ws://legacy"}),
            ])
            result = await provider.start("profile-2")
            self.assertEqual(result["webSocketDebuggerUrl"], "ws://legacy")
            self.assertEqual(
                provider.calls,
                [
                    ("GET", "/browsers/profile-2/debugger"),
                    ("POST", "/browsers/profile-2"),
                    ("POST", "/browsers/profile-2/start"),
                    ("GET", "/browsers/profile-2/debugger"),
                ],
            )

        asyncio.run(scenario())

    def test_stop_prefers_delete_endpoint(self):
        async def scenario():
            provider = _FakeNSTBrowserProvider([
                ("DELETE", "/browsers/profile-3", {"ok": True}),
            ])
            result = await provider.stop("profile-3")
            self.assertEqual(result["ok"], True)
            self.assertEqual(provider.calls, [("DELETE", "/browsers/profile-3")])

        asyncio.run(scenario())

    def test_stop_falls_back_to_post_stop_endpoint(self):
        async def scenario():
            provider = _FakeNSTBrowserProvider([
                ("DELETE", "/browsers/profile-4", BrowserProviderError("browser_provider_http_error", "405")),
                ("POST", "/browsers/profile-4/stop", {"ok": True}),
            ])
            result = await provider.stop("profile-4")
            self.assertEqual(result["ok"], True)
            self.assertEqual(
                provider.calls,
                [
                    ("DELETE", "/browsers/profile-4"),
                    ("POST", "/browsers/profile-4/stop"),
                ],
            )

        asyncio.run(scenario())

    def test_headers_follow_runtime_config_without_recreating_provider(self):
        provider = NSTBrowserProvider(base_url="http://127.0.0.1:8848/api/v2")
        config._config["nst_browser"] = {
            "base_url": "http://127.0.0.1:8848/api/v2",
            "api_key": "first-key",
        }

        self.assertEqual(provider._headers, {"x-api-key": "first-key"})

        config.nst_browser_api_key = "second-key"
        self.assertEqual(provider._headers, {"x-api-key": "second-key"})

        config.nst_browser_api_key = ""
        self.assertEqual(provider._headers, {})


if __name__ == "__main__":
    unittest.main()
