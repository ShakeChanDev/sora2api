"""Regression tests for browser auth persistence."""
import asyncio
import os
import tempfile
import unittest

from src.core.database import Database
from src.core.models import RequestLog, Token


class DatabaseBrowserStateTests(unittest.TestCase):
    """Verify browser/auth metadata persists without schema errors."""

    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.db = Database(self.db_path)
        asyncio.run(self.db.init_db({}))

    def tearDown(self):
        if os.path.exists(self.db_path):
            os.unlink(self.db_path)

    def test_browser_state_and_structured_events_persist(self):
        async def scenario():
            token_id = await self.db.add_token(Token(token="tok", email="user@example.com", name="user"))
            await self.db.update_token_browser_state(
                token_id=token_id,
                browser_provider="nst",
                browser_profile_id="profile-1",
                account_status="ready",
                last_auth_result="success",
                last_egress_binding="binding-1",
            )
            attempt_id = await self.db.create_mutation_attempt(
                token_id=token_id,
                task_id="task_1",
                mutation_type="video_submit",
                strategy="page_execute",
                stage="auth_refresh",
                status="running",
            )
            await self.db.update_mutation_attempt(attempt_id, status="succeeded", stage="completed")
            await self.db.create_task_event(
                task_id="task_1",
                token_id=token_id,
                event_type="auth_refresh",
                stage="auth_refresh",
                status="success",
                message="ok",
            )
            await self.db.create_error_attribution(
                task_id="task_1",
                token_id=token_id,
                mutation_type="video_submit",
                stage="mutation_submit",
                error_code="cloudflare_challenge",
                error_reason="challenge",
            )
            await self.db.log_request(
                RequestLog(
                    token_id=token_id,
                    task_id="task_1",
                    operation="generate",
                    request_body="{}",
                    response_body="{}",
                    stage="polling",
                    trigger_source="server",
                    is_redacted=True,
                    status_code=200,
                    duration=1.0,
                )
            )
            token = await self.db.get_token(token_id)
            logs = await self.db.get_recent_logs(5)
            return token, logs

        token, logs = asyncio.run(scenario())
        self.assertEqual(token.browser_provider, "nst")
        self.assertEqual(token.browser_profile_id, "profile-1")
        self.assertEqual(token.account_status, "ready")
        self.assertEqual(token.last_auth_result, "success")
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0]["stage"], "polling")
        self.assertEqual(logs[0]["trigger_source"], "server")


if __name__ == "__main__":
    unittest.main()
