"""Regression tests for browser auth persistence."""
import asyncio
import os
import tempfile
import unittest
import aiosqlite

from src.core.database import DEFAULT_NST_BROWSER_API_KEY, Database
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

    def test_legacy_token_egress_columns_are_removed_during_migration(self):
        fd, legacy_db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        legacy_db = Database(legacy_db_path)
        try:
            asyncio.run(legacy_db.init_db({}))

            async def scenario():
                async with aiosqlite.connect(legacy_db_path) as raw_db:
                    await raw_db.execute("PRAGMA foreign_keys = OFF")
                    await raw_db.execute("DROP TABLE IF EXISTS tokens")
                    await raw_db.execute("""
                        CREATE TABLE tokens (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            token TEXT UNIQUE NOT NULL,
                            token_hash TEXT,
                            email TEXT NOT NULL,
                            username TEXT NOT NULL,
                            name TEXT NOT NULL,
                            st TEXT,
                            rt TEXT,
                            client_id TEXT,
                            proxy_url TEXT,
                            remark TEXT,
                            expiry_time TIMESTAMP,
                            is_active BOOLEAN DEFAULT 1,
                            cooled_until TIMESTAMP,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            last_used_at TIMESTAMP,
                            use_count INTEGER DEFAULT 0,
                            plan_type TEXT,
                            plan_title TEXT,
                            subscription_end TIMESTAMP,
                            sora2_supported BOOLEAN,
                            sora2_invite_code TEXT,
                            sora2_redeemed_count INTEGER DEFAULT 0,
                            sora2_total_count INTEGER DEFAULT 0,
                            sora2_remaining_count INTEGER DEFAULT 0,
                            sora2_cooldown_until TIMESTAMP,
                            image_enabled BOOLEAN DEFAULT 1,
                            video_enabled BOOLEAN DEFAULT 1,
                            image_concurrency INTEGER DEFAULT -1,
                            video_concurrency INTEGER DEFAULT -1,
                            is_expired BOOLEAN DEFAULT 0,
                            disabled_reason TEXT,
                            browser_provider TEXT,
                            browser_profile_id TEXT,
                            sora_available BOOLEAN,
                            account_status TEXT,
                            last_auth_refresh_at TIMESTAMP,
                            last_auth_result TEXT,
                            last_auth_error_reason TEXT,
                            last_challenge_reason TEXT,
                            last_browser_user_agent TEXT,
                            last_device_id TEXT,
                            last_egress_binding TEXT,
                            last_egress_status TEXT,
                            last_egress_probe_at TIMESTAMP,
                            last_egress_probe_details TEXT,
                            last_auth_page_url TEXT
                        )
                    """)
                    await raw_db.execute("""
                        INSERT INTO tokens (
                            id, token, token_hash, email, username, name, proxy_url,
                            browser_provider, browser_profile_id, account_status,
                            last_auth_result, last_auth_page_url,
                            last_egress_binding, last_egress_status
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        1,
                        secret_codec.encrypt("tok"),
                        secret_codec.hash_secret("tok"),
                        "user@example.com",
                        "legacy-user",
                        "Legacy User",
                        "http://proxy:8080",
                        "nst",
                        "profile-1",
                        "ready",
                        "success",
                        "https://sora.chatgpt.com/drafts",
                        "binding-1",
                        "proven",
                    ))
                    await raw_db.commit()

                await legacy_db.check_and_migrate_db({})

                async with aiosqlite.connect(legacy_db_path) as raw_db:
                    columns_cursor = await raw_db.execute("PRAGMA table_info(tokens)")
                    columns = [row[1] for row in await columns_cursor.fetchall()]
                    token_cursor = await raw_db.execute("""
                        SELECT proxy_url, browser_provider, browser_profile_id, last_auth_result, last_auth_page_url
                        FROM tokens
                        WHERE id = 1
                    """)
                    token_row = await token_cursor.fetchone()

                token = await legacy_db.get_token(1)
                return columns, token_row, token

            columns, token_row, token = asyncio.run(scenario())
            self.assertNotIn("last_egress_binding", columns)
            self.assertNotIn("last_egress_status", columns)
            self.assertNotIn("last_egress_probe_at", columns)
            self.assertNotIn("last_egress_probe_details", columns)
            self.assertIn("last_auth_context_hash", columns)
            self.assertIn("last_auth_context_expires_at", columns)
            self.assertEqual(token_row[0], "http://proxy:8080")
            self.assertEqual(token_row[1], "nst")
            self.assertEqual(token_row[2], "profile-1")
            self.assertEqual(token_row[3], "success")
            self.assertEqual(token_row[4], "https://sora.chatgpt.com/drafts")
            self.assertEqual(token.token, "tok")
            self.assertEqual(token.browser_provider, "nst")
            self.assertEqual(token.browser_profile_id, "profile-1")
            self.assertEqual(token.account_status, "ready")
            self.assertEqual(token.last_auth_result, "success")
            self.assertEqual(token.last_auth_page_url, "https://sora.chatgpt.com/drafts")
        finally:
            if os.path.exists(legacy_db_path):
                os.unlink(legacy_db_path)

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

    def test_admin_config_persists_nst_browser_api_key(self):
        async def scenario():
            await self.db.init_config_from_toml({})
            admin_config = await self.db.get_admin_config()
            default_key = admin_config.nst_browser_api_key
            admin_config.nst_browser_api_key = "updated-nst-key"
            await self.db.update_admin_config(admin_config)
            updated_config = await self.db.get_admin_config()
            return default_key, updated_config

        default_key, updated_config = asyncio.run(scenario())
        self.assertEqual(default_key, DEFAULT_NST_BROWSER_API_KEY)
        self.assertEqual(updated_config.nst_browser_api_key, "updated-nst-key")

    def test_admin_config_migration_backfills_nst_browser_api_key(self):
        fd, legacy_db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        legacy_db = Database(legacy_db_path)
        try:
            asyncio.run(legacy_db.init_db({}))

            async def scenario():
                async with aiosqlite.connect(legacy_db_path) as raw_db:
                    await raw_db.execute("DROP TABLE IF EXISTS admin_config")
                    await raw_db.execute("""
                        CREATE TABLE admin_config (
                            id INTEGER PRIMARY KEY DEFAULT 1,
                            admin_username TEXT DEFAULT 'admin',
                            admin_password TEXT DEFAULT 'admin',
                            api_key TEXT DEFAULT 'han1234',
                            error_ban_threshold INTEGER DEFAULT 3,
                            task_retry_enabled BOOLEAN DEFAULT 1,
                            task_max_retries INTEGER DEFAULT 3,
                            auto_disable_on_401 BOOLEAN DEFAULT 1,
                            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                    """)
                    await raw_db.execute("""
                        INSERT INTO admin_config (
                            id, admin_username, admin_password, api_key,
                            error_ban_threshold, task_retry_enabled, task_max_retries, auto_disable_on_401
                        )
                        VALUES (1, 'admin', 'admin', 'han1234', 3, 1, 3, 1)
                    """)
                    await raw_db.commit()

                await legacy_db.check_and_migrate_db({})

                async with aiosqlite.connect(legacy_db_path) as raw_db:
                    columns_cursor = await raw_db.execute("PRAGMA table_info(admin_config)")
                    columns = [row[1] for row in await columns_cursor.fetchall()]
                    value_cursor = await raw_db.execute(
                        "SELECT nst_browser_api_key FROM admin_config WHERE id = 1"
                    )
                    value_row = await value_cursor.fetchone()

                admin_config = await legacy_db.get_admin_config()
                return columns, value_row[0], admin_config

            columns, stored_key, admin_config = asyncio.run(scenario())
            self.assertIn("nst_browser_api_key", columns)
            self.assertEqual(stored_key, DEFAULT_NST_BROWSER_API_KEY)
            self.assertEqual(admin_config.nst_browser_api_key, DEFAULT_NST_BROWSER_API_KEY)
        finally:
            if os.path.exists(legacy_db_path):
                os.unlink(legacy_db_path)


if __name__ == "__main__":
    unittest.main()
