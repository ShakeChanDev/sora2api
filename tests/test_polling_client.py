"""Tests for task-scoped polling auth refresh."""
import asyncio
import json
import unittest
from unittest.mock import patch

from src.services.browser_provider import EgressBinding, PollingContext
from src.services.polling_client import PollingClient, PollingClientError


class _FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


class _FakeSession:
    responses = []
    requests = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url, headers=None, proxy=None, timeout=None):
        if not self.responses:
            raise RuntimeError("no fake responses configured")
        self.requests.append({
            "url": url,
            "headers": headers or {},
            "proxy": proxy,
            "timeout": timeout,
        })
        return self.responses.pop(0)


class _FakeDb:
    def __init__(self):
        self.logs = []
        self.log_updates = []
        self.task_updates = []
        self.tasks = {}
        self.task_events = []

    async def log_request(self, log):
        self.logs.append(log)
        return len(self.logs)

    async def update_request_log(self, log_id, response_body=None, status_code=None, duration=None):
        self.log_updates.append((log_id, response_body, status_code, duration))

    async def update_task_polling_context(self, task_id, polling_context, auth_snapshot_id=None):
        self.task_updates.append((task_id, polling_context, auth_snapshot_id))
        self.tasks[task_id] = polling_context

    async def get_task(self, task_id):
        payload = self.tasks.get(task_id)
        if payload is None:
            return None
        return type("Task", (), {"polling_context": payload})

    async def create_task_event(self, **kwargs):
        self.task_events.append(kwargs)
        return len(self.task_events)


class _FakeProxyManager:
    def __init__(self, video_proxy_url=None, fallback_proxy_url=None):
        self.video_proxy_url = video_proxy_url
        self.fallback_proxy_url = fallback_proxy_url
        self.video_calls = 0
        self.fallback_calls = 0

    async def get_video_proxy_url(self, token_id=None):
        self.video_calls += 1
        return self.video_proxy_url

    async def get_proxy_url(self, token_id=None, proxy_url=None):
        self.fallback_calls += 1
        return self.fallback_proxy_url


class _FakeAuthContext:
    def __init__(self, polling_context):
        self._polling_context = polling_context
        self.auth_context_hash = "auth-hash"

    def to_polling_context(self):
        return self._polling_context


class _FakeMutationExecutor:
    def __init__(self, polling_context):
        self.polling_context = polling_context
        self.refresh_calls = 0

    async def refresh_polling_context(self, token_id, preferred_url=None, task_id=None, flow=None):
        self.refresh_calls += 1
        return _FakeAuthContext(self.polling_context)


class PollingClientTests(unittest.TestCase):
    """Verify one-shot auth refresh on steady-state polling."""

    def setUp(self):
        binding = EgressBinding(
            provider="nst",
            profile_id="profile-1",
            proxy_url=None,
            page_url="https://sora.chatgpt.com/drafts",
            same_network_identity_proven=False,
        )
        self.polling_context = PollingContext(
            access_token="at",
            cookie_header="cookie=1",
            user_agent="ua",
            device_id="device",
            profile_id="profile-1",
            page_url="https://sora.chatgpt.com/explore",
            referer="https://sora.chatgpt.com/explore",
            sec_fetch_site="same-origin",
            sec_fetch_mode="cors",
            sec_fetch_dest="empty",
            sec_ch_ua='"Chromium";v="143", "Google Chrome";v="143"',
            sec_ch_ua_mobile="?0",
            sec_ch_ua_platform='"Windows"',
            egress_binding=binding,
        )

    def test_refresh_once_on_403_then_succeeds(self):
        async def scenario():
            db = _FakeDb()
            mutation_executor = _FakeMutationExecutor(self.polling_context)
            proxy_manager = _FakeProxyManager(video_proxy_url="http://token-proxy:8080", fallback_proxy_url="http://global-proxy:8080")
            client = PollingClient(db, proxy_manager, mutation_executor, base_url="https://example.com")
            _FakeSession.requests = []
            _FakeSession.responses = [
                _FakeResponse(403, {"error": "forbidden"}),
                _FakeResponse(200, [{"id": "task_1"}]),
            ]
            with patch("src.services.polling_client.AsyncSession", return_value=_FakeSession()):
                payload, polling_context = await client.get_pending_tasks("task_1", 1, "at", self.polling_context)
            self.assertEqual(payload[0]["id"], "task_1")
            self.assertEqual(mutation_executor.refresh_calls, 1)
            self.assertIsNotNone(polling_context)
            self.assertEqual(len(db.task_updates), 1)
            self.assertEqual(len(db.logs), 0)
            self.assertEqual(len(db.log_updates), 0)
            self.assertEqual(_FakeSession.requests[-1]["url"], "https://example.com/nf/pending/v2")
            self.assertEqual(_FakeSession.requests[-1]["headers"]["referer"], "https://sora.chatgpt.com/explore")
            self.assertEqual(_FakeSession.requests[-1]["headers"]["sec-fetch-site"], "same-origin")
            self.assertEqual(_FakeSession.requests[-1]["headers"]["sec-ch-ua-platform"], '"Windows"')
            self.assertNotIn("openai-sentinel-token", _FakeSession.requests[-1]["headers"])
            self.assertEqual(_FakeSession.requests[-1]["proxy"], "http://token-proxy:8080")
            self.assertEqual(proxy_manager.video_calls, 2)
            self.assertEqual(proxy_manager.fallback_calls, 0)
            self.assertGreaterEqual(len(db.task_events), 3)

        asyncio.run(scenario())

    def test_refresh_failure_raises_structured_error(self):
        async def scenario():
            db = _FakeDb()
            mutation_executor = _FakeMutationExecutor(self.polling_context)
            client = PollingClient(db, _FakeProxyManager(video_proxy_url="http://token-proxy:8080"), mutation_executor, base_url="https://example.com")
            _FakeSession.responses = [
                _FakeResponse(403, {"error": "forbidden"}),
                _FakeResponse(403, {"error": "still forbidden"}),
            ]
            with patch("src.services.polling_client.AsyncSession", return_value=_FakeSession()):
                with self.assertRaises(PollingClientError) as ctx:
                    await client.get_pending_tasks("task_1", 1, "at", self.polling_context)
            self.assertEqual(ctx.exception.code, "polling_pending_unauthorized")
            self.assertEqual(mutation_executor.refresh_calls, 1)

        asyncio.run(scenario())

    def test_video_drafts_uses_v2_endpoint_and_validates_schema(self):
        async def scenario():
            db = _FakeDb()
            mutation_executor = _FakeMutationExecutor(self.polling_context)
            client = PollingClient(db, _FakeProxyManager(video_proxy_url="http://token-proxy:8080"), mutation_executor, base_url="https://example.com")
            _FakeSession.requests = []
            _FakeSession.responses = [
                _FakeResponse(200, {"items": [{"task_id": "task_1"}]}),
            ]
            with patch("src.services.polling_client.AsyncSession", return_value=_FakeSession()):
                payload, _ = await client.get_video_drafts("task_1", 1, "at", self.polling_context)
            self.assertEqual(payload["items"][0]["task_id"], "task_1")
            self.assertEqual(_FakeSession.requests[-1]["url"], "https://example.com/project_y/profile/drafts/v2?limit=15")

        asyncio.run(scenario())

    def test_video_drafts_invalid_schema_raises_structured_error(self):
        async def scenario():
            db = _FakeDb()
            mutation_executor = _FakeMutationExecutor(self.polling_context)
            client = PollingClient(db, _FakeProxyManager(video_proxy_url="http://token-proxy:8080"), mutation_executor, base_url="https://example.com")
            _FakeSession.responses = [
                _FakeResponse(200, {"unexpected": True}),
            ]
            with patch("src.services.polling_client.AsyncSession", return_value=_FakeSession()):
                with self.assertRaises(PollingClientError) as ctx:
                    await client.get_video_drafts("task_1", 1, "at", self.polling_context)
            self.assertEqual(ctx.exception.code, "polling_drafts_schema_invalid")

        asyncio.run(scenario())

    def test_missing_video_proxy_binding_raises_structured_error(self):
        async def scenario():
            db = _FakeDb()
            mutation_executor = _FakeMutationExecutor(self.polling_context)
            client = PollingClient(db, _FakeProxyManager(video_proxy_url=None, fallback_proxy_url="http://global-proxy:8080"), mutation_executor, base_url="https://example.com")
            with self.assertRaises(PollingClientError) as ctx:
                await client.get_pending_tasks("task_1", 1, "at", self.polling_context)
            self.assertEqual(ctx.exception.code, "browser_proxy_binding_required")

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
