"""Regression tests for browser auth persistence."""
import asyncio
import os
import tempfile
import unittest
import aiosqlite

from src.core.database import Database
from src.core.models import RequestLog, Task, Token
from src.core.secret_codec import secret_codec


class DatabaseBrowserStateTests(unittest.TestCase):
    """Verify browser/auth metadata persists without schema errors."""

    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        secret_codec.configure("unit-test-secret")
        self.db = Database(self.db_path)
        asyncio.run(self.db.init_db({}))

    def tearDown(self):
        secret_codec.configure("")
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
            await self.db.create_task(
                task=Task(
                    task_id="task_1",
                    token_id=token_id,
                    model="sora2-landscape-10s",
                    prompt="test",
                    status="processing",
                    progress=0.0,
                    current_stage="polling",
                    auth_snapshot_id="auth-1",
                    polling_context='{"access_token":"tok","cookie_header":"cookie=1","user_agent":"ua","device_id":"dev","profile_id":"profile-1","expires_at":null,"refreshed_at":null,"egress_binding":{"provider":"nst","profile_id":"profile-1","proxy_url":null,"page_url":"https://sora.chatgpt.com/drafts","proxy_policy":null,"browser_observation":null,"server_observation":null,"same_network_identity_proven":false}}',
                )
            )
            await self.db.update_task("task_1", "completed", 100.0, result_urls='["https://example.com/video.mp4"]')
            token = await self.db.get_token(token_id)
            logs = await self.db.get_recent_logs(5)
            task = await self.db.get_task("task_1")
            async with aiosqlite.connect(self.db_path) as raw_db:
                token_cursor = await raw_db.execute("SELECT token FROM tokens WHERE id = ?", (token_id,))
                token_row = await token_cursor.fetchone()
                task_cursor = await raw_db.execute("SELECT polling_context FROM tasks WHERE task_id = ?", ("task_1",))
                task_row = await task_cursor.fetchone()
            return token, logs, task, token_row, task_row

        token, logs, task, token_row, task_row = asyncio.run(scenario())
        self.assertEqual(token.browser_provider, "nst")
        self.assertEqual(token.browser_profile_id, "profile-1")
        self.assertEqual(token.account_status, "ready")
        self.assertEqual(token.last_auth_result, "success")
        self.assertIsNotNone(token_row)
        self.assertIsNotNone(task_row)
        self.assertTrue(token_row[0].startswith("enc:v1:"))
        self.assertTrue(task_row[0].startswith("enc:v1:"))
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0]["stage"], "polling")
        self.assertEqual(logs[0]["trigger_source"], "server")
        self.assertEqual(task.current_stage, "completed")
        self.assertEqual(task.auth_snapshot_id, "auth-1")
        self.assertIn('"profile_id":"profile-1"', task.polling_context)

    def test_migration_drops_legacy_token_egress_columns(self):
        async def scenario():
            async with aiosqlite.connect(self.db_path) as raw_db:
                await raw_db.execute("ALTER TABLE tokens ADD COLUMN last_egress_binding TEXT")
                await raw_db.execute("ALTER TABLE tokens ADD COLUMN last_egress_status TEXT")
                await raw_db.execute("ALTER TABLE tokens ADD COLUMN last_egress_probe_at TIMESTAMP")
                await raw_db.execute("ALTER TABLE tokens ADD COLUMN last_egress_probe_details TEXT")
                await raw_db.commit()

            token_id = await self.db.add_token(
                Token(
                    token="tok",
                    email="user@example.com",
                    name="user",
                    proxy_url="http://proxy:8080",
                )
            )
            await self.db.update_token_browser_state(
                token_id=token_id,
                browser_provider="nst",
                browser_profile_id="profile-1",
                account_status="ready",
                last_auth_result="success",
                last_auth_context_hash="auth-hash-1",
                last_auth_page_url="https://sora.chatgpt.com/drafts",
            )

            async with aiosqlite.connect(self.db_path) as raw_db:
                await raw_db.execute(
                    """
                    UPDATE tokens
                    SET last_egress_binding = ?, last_egress_status = ?, last_egress_probe_details = ?
                    WHERE id = ?
                    """,
                    ("binding-1", "proven", '{"source":"legacy"}', token_id),
                )
                await raw_db.commit()

            await self.db.check_and_migrate_db({})
            token = await self.db.get_token(token_id)

            async with aiosqlite.connect(self.db_path) as raw_db:
                cursor = await raw_db.execute("PRAGMA table_info(tokens)")
                columns = [row[1] for row in await cursor.fetchall()]
                row_cursor = await raw_db.execute(
                    """
                    SELECT token, proxy_url, browser_provider, browser_profile_id, account_status,
                           last_auth_context_hash, last_auth_page_url
                    FROM tokens
                    WHERE id = ?
                    """,
                    (token_id,),
                )
                row = await row_cursor.fetchone()
            return token, columns, row

        token, columns, row = asyncio.run(scenario())
        self.assertIsNotNone(row)
        self.assertNotIn("last_egress_binding", columns)
        self.assertNotIn("last_egress_status", columns)
        self.assertNotIn("last_egress_probe_at", columns)
        self.assertNotIn("last_egress_probe_details", columns)
        self.assertEqual(token.token, "tok")
        self.assertEqual(token.proxy_url, "http://proxy:8080")
        self.assertEqual(token.browser_provider, "nst")
        self.assertEqual(token.browser_profile_id, "profile-1")
        self.assertEqual(token.account_status, "ready")
        self.assertEqual(token.last_auth_context_hash, "auth-hash-1")
        self.assertEqual(token.last_auth_page_url, "https://sora.chatgpt.com/drafts")
        self.assertTrue(row[0].startswith("enc:v1:"))
        self.assertEqual(row[1], "http://proxy:8080")
        self.assertEqual(row[2], "nst")
        self.assertEqual(row[3], "profile-1")
        self.assertEqual(row[4], "ready")
        self.assertEqual(row[5], "auth-hash-1")
        self.assertEqual(row[6], "https://sora.chatgpt.com/drafts")

    def test_recent_logs_collapse_to_primary_task_record(self):
        async def scenario():
            token_id = await self.db.add_token(Token(token="tok", email="user@example.com", name="user"))
            primary_log_id = await self.db.log_request(
                RequestLog(
                    token_id=token_id,
                    task_id="task_2",
                    operation="generate_video",
                    request_body="{}",
                    response_body='{"result_urls":["https://example.com/video.mp4"]}',
                    stage="generate_video",
                    trigger_source="server",
                    is_redacted=True,
                    status_code=200,
                    duration=12.3,
                )
            )
            await self.db.log_request(
                RequestLog(
                    token_id=token_id,
                    task_id="task_2",
                    operation="pending_v2",
                    request_body="{}",
                    response_body="{}",
                    stage="polling",
                    trigger_source="server",
                    is_redacted=True,
                    status_code=200,
                    duration=1.0,
                )
            )
            await self.db.log_request(
                RequestLog(
                    token_id=token_id,
                    task_id="task_2",
                    operation="drafts_lookup",
                    request_body="{}",
                    response_body="{}",
                    stage="drafts_lookup",
                    trigger_source="server",
                    is_redacted=True,
                    status_code=200,
                    duration=1.0,
                )
            )
            logs = await self.db.get_recent_logs(10)
            return primary_log_id, logs

        primary_log_id, logs = asyncio.run(scenario())
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0]["id"], primary_log_id)
        self.assertEqual(logs[0]["operation"], "generate_video")


if __name__ == "__main__":
    unittest.main()
