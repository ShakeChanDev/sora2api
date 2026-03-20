"""Policy tests for high-risk mutation execution."""
import asyncio
import unittest
from types import SimpleNamespace

from src.services.browser_provider import AuthContext, BrowserProviderError, EgressBinding
from src.services.mutation_executor import MutationExecutor, MutationStrategy, MutationType


class _FakeDb:
    def __init__(self, active_tokens, token_by_id):
        self._active_tokens = active_tokens
        self._token_by_id = token_by_id
        self.browser_state_updates = []

    async def get_active_tokens(self):
        return list(self._active_tokens)

    async def get_token(self, token_id):
        return self._token_by_id.get(token_id)

    async def count_active_tokens(self):
        return len(self._active_tokens)

    async def update_token_browser_state(self, token_id, **kwargs):
        self.browser_state_updates.append((token_id, kwargs))


class _FakeProvider:
    provider_name = "nst"


class MutationExecutorPolicyTests(unittest.TestCase):
    """Verify conservative mutation policy gates."""

    def test_duplicate_profile_binding_is_rejected(self):
        async def scenario():
            token_a = SimpleNamespace(id=1, is_active=True, browser_provider="nst", browser_profile_id="profile-1", account_status="ready")
            token_b = SimpleNamespace(id=2, is_active=True, browser_provider="nst", browser_profile_id="profile-1", account_status="ready")
            db = _FakeDb([token_a, token_b], {1: token_a, 2: token_b})
            executor = MutationExecutor(db, _FakeProvider(), proxy_manager=None)
            with self.assertRaises(BrowserProviderError) as ctx:
                await executor._resolve_profile(1)
            self.assertEqual(ctx.exception.code, "duplicate_profile_binding")
            self.assertTrue(any(update[1].get("account_status") == "duplicate_profile_binding" for update in db.browser_state_updates))

        asyncio.run(scenario())

    def test_default_profile_requires_explicit_binding_when_multiple_tokens(self):
        async def scenario():
            token_a = SimpleNamespace(id=1, is_active=True, browser_provider="nst", browser_profile_id=None, account_status="ready")
            token_b = SimpleNamespace(id=2, is_active=True, browser_provider="nst", browser_profile_id="profile-2", account_status="ready")
            db = _FakeDb([token_a, token_b], {1: token_a, 2: token_b})
            executor = MutationExecutor(db, _FakeProvider(), proxy_manager=None)
            from src.core.config import config

            original_enabled = config.browser_enabled
            original_default = config.browser_default_profile_id
            original_enforce = config.browser_enforce_token_profile_binding
            try:
                config._config["browser"]["enabled"] = True
                config._config["browser"]["default_profile_id"] = "default-profile"
                config._config["browser"]["enforce_token_profile_binding"] = True
                with self.assertRaises(BrowserProviderError) as ctx:
                    await executor._resolve_profile(1)
                self.assertEqual(ctx.exception.code, "browser_profile_misconfigured")
            finally:
                config._config["browser"]["enabled"] = original_enabled
                config._config["browser"]["default_profile_id"] = original_default
                config._config["browser"]["enforce_token_profile_binding"] = original_enforce

        asyncio.run(scenario())

    def test_replay_rejected_without_proven_identity(self):
        egress_binding = EgressBinding(
            provider="nst",
            profile_id="profile-1",
            proxy_url=None,
            page_url="https://sora.chatgpt.com/drafts",
            same_network_identity_proven=False,
        )
        auth_context = AuthContext(
            access_token="token",
            cookie_header="cookie=1",
            user_agent="ua",
            device_id="device",
            sentinel_token="sentinel",
            refreshed_at=__import__("datetime").datetime.utcnow(),
            provider="nst",
            profile_id="profile-1",
            page_url="https://sora.chatgpt.com/drafts",
            egress_binding=egress_binding,
        )
        executor = MutationExecutor(_FakeDb([], {}), _FakeProvider(), proxy_manager=None)
        with self.assertRaises(BrowserProviderError) as ctx:
            executor.assert_replay_allowed(
                MutationType.VIDEO_SUBMIT,
                MutationStrategy.PAGE_REFRESH_THEN_REPLAY,
                auth_context,
            )
        self.assertEqual(ctx.exception.code, "replay_not_allowed")

    def test_video_token_requires_explicit_proxy_binding(self):
        async def scenario():
            token_obj = SimpleNamespace(
                id=1,
                is_active=True,
                browser_provider="nst",
                browser_profile_id="profile-1",
                proxy_url=None,
                account_status="ready",
            )
            db = _FakeDb([token_obj], {1: token_obj})
            executor = MutationExecutor(db, _FakeProvider(), proxy_manager=None)
            with self.assertRaises(BrowserProviderError) as ctx:
                await executor.ensure_video_token_binding(1)
            self.assertEqual(ctx.exception.code, "browser_proxy_binding_required")

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
