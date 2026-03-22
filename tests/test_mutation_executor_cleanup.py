"""Lifecycle cleanup tests for browser-backed mutations."""
import asyncio
import unittest
from datetime import datetime
from types import SimpleNamespace

from src.services.browser_provider import (
    AuthContext,
    BrowserConnection,
    BrowserMutationRequest,
    BrowserMutationResponse,
    BrowserPageContext,
    BrowserProviderError,
    EgressBinding,
)
from src.services.mutation_executor import MutationExecutor, MutationType


class _FakeDb:
    def __init__(self, token_obj):
        self._token = token_obj
        self.task_events = []
        self.mutation_attempts = []
        self.browser_state_updates = []
        self.error_attributions = []
        self.task_stage_updates = []
        self.token_updates = []

    async def get_active_tokens(self):
        return [self._token]

    async def get_token(self, token_id):
        if token_id == self._token.id:
            return self._token
        return None

    async def count_active_tokens(self):
        return 1

    async def update_token_browser_state(self, token_id, **kwargs):
        self.browser_state_updates.append((token_id, kwargs))

    async def update_token(self, token_id, token):
        self.token_updates.append((token_id, token))

    async def create_mutation_attempt(self, **kwargs):
        self.mutation_attempts.append(("create", kwargs))
        return len(self.mutation_attempts)

    async def update_mutation_attempt(self, attempt_id, **kwargs):
        self.mutation_attempts.append(("update", attempt_id, kwargs))

    async def create_task_event(self, **kwargs):
        self.task_events.append(kwargs)
        return len(self.task_events)

    async def create_error_attribution(self, **kwargs):
        self.error_attributions.append(kwargs)

    async def update_task_stage(self, **kwargs):
        self.task_stage_updates.append(kwargs)


class _FakeProvider:
    provider_name = "nst"

    def __init__(self, refresh_errors=None, stop_error=None):
        self.refresh_errors = list(refresh_errors or [])
        self.stop_error = stop_error
        self.disconnect_calls = []
        self.stop_calls = []
        self.connect_calls = []

    async def start(self, profile_id):
        return {"profileId": profile_id}

    async def stop(self, profile_id):
        self.stop_calls.append(profile_id)
        if self.stop_error:
            raise self.stop_error
        return {"profileId": profile_id}

    async def connect_profile(self, profile_id, preferred_url=None):
        self.connect_calls.append((profile_id, preferred_url))
        return BrowserConnection(
            provider=self.provider_name,
            profile_id=profile_id,
            debugger_url="ws://debugger",
            proxy_url="http://proxy:8080",
            browser=object(),
            context=None,
            page=SimpleNamespace(url=preferred_url or "https://sora.chatgpt.com/explore"),
            page_id="page-1",
            playwright=None,
        )

    async def readiness_check(self, connection, preferred_url=None):
        page_url = preferred_url or connection.page.url
        return BrowserPageContext(
            profile_id=connection.profile_id,
            page_id="page-1",
            page_url=page_url,
            title="Sora",
            provider=self.provider_name,
        )

    async def get_page_context(self, connection):
        return await self.readiness_check(connection, preferred_url=connection.page.url)

    async def refresh_auth_context(self, connection, flow, preferred_url=None):
        if self.refresh_errors:
            maybe_error = self.refresh_errors.pop(0)
            if maybe_error is not None:
                raise maybe_error
        page_url = preferred_url or connection.page.url
        return AuthContext(
            access_token="access-token",
            cookie_header="cookie=1",
            user_agent="ua",
            device_id="device-id",
            sentinel_token="sentinel-token",
            refreshed_at=datetime.utcnow(),
            provider=self.provider_name,
            profile_id=connection.profile_id,
            page_url=page_url,
            egress_binding=EgressBinding(
                provider=self.provider_name,
                profile_id=connection.profile_id,
                proxy_url=connection.proxy_url,
                page_url=page_url,
                same_network_identity_proven=False,
            ),
        )

    async def fetch_json(self, connection, request, auth_context):
        return BrowserMutationResponse(
            status=200,
            ok=True,
            headers={},
            data={"id": "task-generated"},
            text='{"id":"task-generated"}',
            page_url=auth_context.page_url,
        )

    async def execute_in_page(self, connection, script, arg=None):
        return {}

    async def recover_same_profile(self, profile_id, preferred_url=None):
        return await self.connect_profile(profile_id, preferred_url=preferred_url)

    async def disconnect(self, connection):
        self.disconnect_calls.append(connection.profile_id)


class MutationExecutorCleanupTests(unittest.TestCase):
    def _request_plan(self):
        return [
            BrowserMutationRequest(
                "POST",
                "https://sora.chatgpt.com/backend/nf/create",
                {"kind": "video", "prompt": "prompt"},
                expected_status=200,
            )
        ]

    def _build_executor(self, provider):
        token_obj = SimpleNamespace(
            id=1,
            is_active=True,
            browser_provider="nst",
            browser_profile_id="profile-1",
            proxy_url="http://proxy:8080",
            account_status="ready",
        )
        db = _FakeDb(token_obj)
        return MutationExecutor(db, provider, proxy_manager=None), db

    def test_page_plan_success_disconnects_then_stops_profile(self):
        async def scenario():
            provider = _FakeProvider()
            executor, db = self._build_executor(provider)
            result = await executor._run_page_plan(
                mutation_type=MutationType.VIDEO_SUBMIT,
                token_id=1,
                request_plan=self._request_plan(),
                task_id="task-generated",
                preferred_url="https://sora.chatgpt.com/explore",
            )
            self.assertEqual(result.task_id, "task-generated")
            self.assertEqual(provider.disconnect_calls, ["profile-1"])
            self.assertEqual(provider.stop_calls, ["profile-1"])
            self.assertTrue(db.token_updates)

        asyncio.run(scenario())

    def test_stop_failure_is_recorded_without_overriding_success(self):
        async def scenario():
            provider = _FakeProvider(
                stop_error=BrowserProviderError("browser_provider_http_error", "stop failed")
            )
            executor, db = self._build_executor(provider)
            result = await executor._run_page_plan(
                mutation_type=MutationType.VIDEO_SUBMIT,
                token_id=1,
                request_plan=self._request_plan(),
                task_id="task-generated",
                preferred_url="https://sora.chatgpt.com/explore",
            )
            self.assertEqual(result.task_id, "task-generated")
            self.assertEqual(provider.disconnect_calls, ["profile-1"])
            self.assertEqual(provider.stop_calls, ["profile-1"])
            self.assertTrue(any(event["event_type"] == "browser_stop_failed" for event in db.task_events))

        asyncio.run(scenario())

    def test_refresh_polling_context_retries_with_cleanup_between_attempts(self):
        async def scenario():
            provider = _FakeProvider(
                refresh_errors=[BrowserProviderError("TARGET_CLOSED", "target closed"), None]
            )
            executor, _ = self._build_executor(provider)
            auth_context = await executor.refresh_polling_context(
                token_id=1,
                preferred_url="https://sora.chatgpt.com/drafts",
                task_id="task-polling",
            )
            self.assertEqual(auth_context.profile_id, "profile-1")
            self.assertEqual(provider.disconnect_calls, ["profile-1", "profile-1"])
            self.assertEqual(provider.stop_calls, ["profile-1", "profile-1"])
            self.assertEqual(len(provider.connect_calls), 2)

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
