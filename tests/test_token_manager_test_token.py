"""Tests for Windows-safe token testing semantics."""
import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from src.api import admin
from src.services.token_manager import TokenManager


class _FakeDb:
    def __init__(self, token_obj):
        self.token_obj = token_obj
        self.update_token_calls = []
        self.update_sora2_calls = []
        self.clear_expired_calls = []
        self.mark_expired_calls = []
        self.mark_invalid_calls = []

    async def get_token(self, token_id):
        if self.token_obj.id == token_id:
            return self.token_obj
        return None

    async def update_token(self, token_id, **kwargs):
        self.update_token_calls.append((token_id, kwargs))
        for key, value in kwargs.items():
            setattr(self.token_obj, key, value)

    async def update_token_sora2(self, token_id, supported, invite_code=None, redeemed_count=0, total_count=0, remaining_count=0):
        payload = {
            "supported": supported,
            "invite_code": invite_code,
            "redeemed_count": redeemed_count,
            "total_count": total_count,
            "remaining_count": remaining_count,
        }
        self.update_sora2_calls.append((token_id, payload))
        self.token_obj.sora2_supported = supported
        self.token_obj.sora2_invite_code = invite_code
        self.token_obj.sora2_redeemed_count = redeemed_count
        self.token_obj.sora2_total_count = total_count
        self.token_obj.sora2_remaining_count = remaining_count

    async def clear_token_expired(self, token_id):
        self.clear_expired_calls.append(token_id)

    async def mark_token_expired(self, token_id):
        self.mark_expired_calls.append(token_id)

    async def mark_token_invalid(self, token_id):
        self.mark_invalid_calls.append(token_id)


class _TestTokenManager(TokenManager):
    def __init__(self, db, *, user_info=None, user_info_error=None, subscription=None, subscription_error=None, sora2_info=None, sora2_info_error=None, remaining_info=None, remaining_error=None):
        super().__init__(db)
        self._user_info = user_info or {"email": "demo@example.com", "username": "demo-user"}
        self._user_info_error = user_info_error
        self._subscription = subscription or {}
        self._subscription_error = subscription_error
        self._sora2_info = sora2_info or {"supported": False, "invite_code": None, "redeemed_count": 0, "total_count": 0}
        self._sora2_info_error = sora2_info_error
        self._remaining_info = remaining_info or {"success": True, "remaining_count": 7}
        self._remaining_error = remaining_error

    async def get_user_info(self, access_token: str, token_id=None, proxy_url=None):
        if self._user_info_error:
            raise self._user_info_error
        return dict(self._user_info)

    async def get_subscription_info(self, token: str, token_id=None, proxy_url=None):
        if self._subscription_error:
            raise self._subscription_error
        return dict(self._subscription)

    async def get_sora2_invite_code(self, access_token: str, token_id=None, proxy_url=None):
        if self._sora2_info_error:
            raise self._sora2_info_error
        return dict(self._sora2_info)

    async def get_sora2_remaining_count(self, access_token: str, token_id=None, proxy_url=None):
        if self._remaining_error:
            raise self._remaining_error
        return dict(self._remaining_info)

    async def check_username_available(self, access_token: str, username: str) -> bool:
        return True

    async def set_username(self, access_token: str, username: str) -> dict:
        return {"username": username}


class TokenManagerTestTokenTests(unittest.TestCase):
    def _make_token(self):
        return SimpleNamespace(
            id=1,
            token="access-token",
            email="demo@example.com",
            username="demo-user",
            plan_type="chatgpt_free",
            plan_title="ChatGPT Free",
            subscription_end=None,
            sora2_supported=True,
            sora2_invite_code="INVITE",
            sora2_redeemed_count=1,
            sora2_total_count=5,
            sora2_remaining_count=3,
            account_status="auth_error",
            last_auth_error_reason="old error",
        )

    def test_subscription_failure_keeps_token_valid(self):
        async def scenario():
            token_obj = self._make_token()
            db = _FakeDb(token_obj)
            manager = _TestTokenManager(
                db,
                subscription_error=RuntimeError("subscription boom"),
                sora2_info={"supported": False, "invite_code": None, "redeemed_count": 0, "total_count": 0},
            )
            result = await manager.test_token(1)
            self.assertTrue(result["valid"])
            self.assertIn("subscription_refresh_failed", result["warnings"][0])
            self.assertEqual(token_obj.account_status, "ready")
            self.assertEqual(token_obj.last_auth_error_reason, "")
            self.assertEqual(db.clear_expired_calls, [1])

        asyncio.run(scenario())

    def test_sora2_failure_keeps_token_valid(self):
        async def scenario():
            token_obj = self._make_token()
            db = _FakeDb(token_obj)
            manager = _TestTokenManager(
                db,
                subscription={"plan_type": "chatgpt_plus", "plan_title": "ChatGPT Plus", "subscription_end": None},
                sora2_info_error=RuntimeError("invite boom"),
            )
            result = await manager.test_token(1)
            self.assertTrue(result["valid"])
            self.assertTrue(any("sora2_info_refresh_failed" in item for item in result["warnings"]))
            self.assertEqual(token_obj.account_status, "ready")
            self.assertEqual(token_obj.last_auth_error_reason, "")
            self.assertEqual(db.update_sora2_calls, [])

        asyncio.run(scenario())

    def test_auth_failure_still_marks_token_invalid(self):
        async def scenario():
            token_obj = self._make_token()
            db = _FakeDb(token_obj)
            manager = _TestTokenManager(
                db,
                user_info_error=ValueError("401 token_invalidated: Token has been invalidated"),
            )
            result = await manager.test_token(1)
            self.assertFalse(result["valid"])
            self.assertEqual(db.mark_expired_calls, [1])
            self.assertEqual(db.mark_invalid_calls, [])

        asyncio.run(scenario())

    def test_logging_failures_do_not_break_validation(self):
        async def scenario():
            token_obj = self._make_token()
            db = _FakeDb(token_obj)
            manager = _TestTokenManager(
                db,
                subscription_error=RuntimeError("subscription boom"),
            )
            with patch("src.services.token_manager.debug_logger.log_warning", side_effect=RuntimeError("logger boom")):
                result = await manager.test_token(1)
            self.assertTrue(result["valid"])
            self.assertEqual(token_obj.account_status, "ready")

        asyncio.run(scenario())


class AdminTokenTestEndpointTests(unittest.TestCase):
    def test_single_test_includes_warnings(self):
        async def scenario():
            fake_manager = SimpleNamespace(
                test_token=AsyncMock(return_value={
                    "valid": True,
                    "message": "Token is valid with warnings",
                    "email": "demo@example.com",
                    "username": "demo-user",
                    "warnings": ["subscription_refresh_failed: boom"],
                })
            )
            with patch.object(admin, "token_manager", fake_manager):
                response = await admin.test_token(1, token="admin-token")
            self.assertEqual(response["status"], "success")
            self.assertEqual(response["warnings"], ["subscription_refresh_failed: boom"])

        asyncio.run(scenario())

    def test_batch_test_counts_warning_results_as_success(self):
        async def scenario():
            fake_db = SimpleNamespace(
                get_all_tokens=AsyncMock(return_value=[SimpleNamespace(id=1, email="demo@example.com")])
            )
            fake_manager = SimpleNamespace(
                test_token=AsyncMock(return_value={
                    "valid": True,
                    "message": "Token is valid with warnings",
                    "warnings": ["subscription_refresh_failed: boom"],
                })
            )
            with patch.object(admin, "db", fake_db), patch.object(admin, "token_manager", fake_manager):
                response = await admin.batch_test_update(token="admin-token")
            self.assertEqual(response["success_count"], 1)
            self.assertEqual(response["failed_count"], 0)
            self.assertEqual(response["results"][0]["warnings"], ["subscription_refresh_failed: boom"])

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
