import unittest
from datetime import datetime

from src.core.models import Token
from src.services.browser_runtime import (
    AuthContext,
    BrowserHandle,
    BrowserReadiness,
    PageContext,
    UpstreamExecutionError,
)
from src.services.mutation_executor import MutationExecutor


class _FakePage:
    def __init__(self):
        self.session_counter = 0

    async def evaluate(self, script, *args):
        if "/api/auth/session" in script:
            self.session_counter += 1
            return {
                "ok": True,
                "status": 200,
                "text": f'{{"accessToken":"page-at-{self.session_counter}"}}',
                "json": {"accessToken": f"page-at-{self.session_counter}"},
            }
        if "typeof window.SentinelSDK" in script:
            return True
        if "window.SentinelSDK.token" in script:
            return f"page-sentinel-{self.session_counter or 1}"
        raise AssertionError(f"Unexpected page.evaluate call: {script}")


class _FakeDb:
    def __init__(self):
        self.snapshots = []

    async def update_token_account_snapshot(self, token_id, **kwargs):
        self.snapshots.append((token_id, kwargs))


class _FakeProvider:
    def __init__(self):
        self.stop_calls = 0
        self.page = _FakePage()

    async def connect_profile(self, profile_id, profile_path):
        return BrowserHandle(
            provider="fake",
            profile_id=profile_id,
            profile_path=profile_path,
            window_id=f"window-{profile_id}",
            connected_at=datetime.now(),
            state="connected",
            page=self.page,
            context=object(),
            driver=object(),
        )

    async def start_profile(self, profile_id, profile_path):
        return await self.connect_profile(profile_id, profile_path)

    async def stop_profile(self, profile_id):
        self.stop_calls += 1

    async def recover_profile(self, profile_id, profile_path):
        return await self.connect_profile(profile_id, profile_path)

    async def readiness_check(self, handle, target_url):
        return BrowserReadiness(
            ready=True,
            page_url=target_url,
            challenge_detected=False,
            sentinel_ready=True,
        )

    async def get_page_context(self, handle, target_url):
        return PageContext(
            page_url=target_url,
            user_agent="fake-ua",
            cookie_header="a=b; oai-did=device-1",
            device_id="device-1",
            session_fetched_at=datetime.now(),
        )

    async def execute_in_page(self, handle, action, payload):
        return {"ok": True, "json": {"id": "page-task"}}


class MutationExecutorTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.db = _FakeDb()
        self.provider = _FakeProvider()
        self.executor = MutationExecutor(self.provider, self.db)
        self.token = Token(
            id=1,
            token="stored-at",
            email="user@example.com",
            browser_profile_id="profile-1",
            browser_profile_path="C:/profiles/profile-1",
        )

    async def test_replay_success_uses_fresh_auth_context(self):
        seen_contexts = []

        async def replay_callable(session):
            seen_contexts.append(session.auth_context)
            return {"id": "replay-task"}

        result = await self.executor.execute(
            self.token,
            mutation_type="video_submit",
            target_url="https://sora.chatgpt.com/explore",
            replay_callable=replay_callable,
            page_callable=None,
        )

        self.assertEqual(result.strategy, "replay_http")
        self.assertEqual(result.task_id, "replay-task")
        self.assertEqual(seen_contexts[0].access_token, "page-at-1")
        self.assertEqual(seen_contexts[0].sentinel_token, "page-sentinel-1")
        self.assertEqual(self.provider.stop_calls, 1)
        self.assertTrue(self.db.snapshots)

    async def test_high_risk_replay_failure_refreshes_auth_before_page_execute(self):
        async def replay_callable(session):
            raise UpstreamExecutionError(
                "curl: (28) Operation timed out after 45014 milliseconds with 0 bytes received",
            )

        async def page_callable(session):
            self.assertEqual(session.auth_context.access_token, "page-at-2")
            self.assertEqual(session.auth_context.sentinel_token, "page-sentinel-2")
            return {"id": "page-task"}

        result = await self.executor.execute(
            self.token,
            mutation_type="video_submit",
            target_url="https://sora.chatgpt.com/explore",
            replay_callable=replay_callable,
            page_callable=page_callable,
        )

        self.assertEqual(result.strategy, "page_execute")
        self.assertEqual(result.task_id, "page-task")
        self.assertEqual(len(result.attempts), 2)
        self.assertFalse(result.attempts[0].success)
        self.assertTrue(result.attempts[1].success)

    async def test_publish_defaults_to_page_execute(self):
        async def page_callable(session):
            return {"id": "publish-task"}

        result = await self.executor.execute(
            self.token,
            mutation_type="publish_execute",
            target_url="https://sora.chatgpt.com/c/library",
            page_callable=page_callable,
        )

        self.assertEqual(result.strategy, "page_execute")
        self.assertEqual(result.task_id, "publish-task")
        self.assertEqual(len(result.attempts), 1)
        self.assertEqual(result.attempts[0].strategy, "page_execute")


if __name__ == "__main__":
    unittest.main()
