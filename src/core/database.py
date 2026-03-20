"""Database storage layer"""
import aiosqlite
import json
from datetime import datetime
from typing import Optional, List, Dict, Any
from pathlib import Path
from .models import (
    Token,
    TokenStats,
    Task,
    RequestLog,
    AdminConfig,
    ProxyConfig,
    WatermarkFreeConfig,
    CacheConfig,
    GenerationConfig,
    TokenRefreshConfig,
    MutationAttempt,
    TaskEvent,
    ErrorAttribution,
)
from .secret_codec import secret_codec

TOKEN_LEGACY_EGRESS_COLUMNS = (
    "last_egress_binding",
    "last_egress_status",
    "last_egress_probe_at",
    "last_egress_probe_details",
)

TOKEN_TABLE_COLUMN_DEFINITIONS = (
    ("id", "INTEGER PRIMARY KEY AUTOINCREMENT"),
    ("token", "TEXT UNIQUE NOT NULL"),
    ("token_hash", "TEXT"),
    ("email", "TEXT NOT NULL"),
    ("username", "TEXT NOT NULL"),
    ("name", "TEXT NOT NULL"),
    ("st", "TEXT"),
    ("rt", "TEXT"),
    ("client_id", "TEXT"),
    ("proxy_url", "TEXT"),
    ("remark", "TEXT"),
    ("expiry_time", "TIMESTAMP"),
    ("is_active", "BOOLEAN DEFAULT 1"),
    ("cooled_until", "TIMESTAMP"),
    ("created_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
    ("last_used_at", "TIMESTAMP"),
    ("use_count", "INTEGER DEFAULT 0"),
    ("plan_type", "TEXT"),
    ("plan_title", "TEXT"),
    ("subscription_end", "TIMESTAMP"),
    ("sora2_supported", "BOOLEAN"),
    ("sora2_invite_code", "TEXT"),
    ("sora2_redeemed_count", "INTEGER DEFAULT 0"),
    ("sora2_total_count", "INTEGER DEFAULT 0"),
    ("sora2_remaining_count", "INTEGER DEFAULT 0"),
    ("sora2_cooldown_until", "TIMESTAMP"),
    ("image_enabled", "BOOLEAN DEFAULT 1"),
    ("video_enabled", "BOOLEAN DEFAULT 1"),
    ("image_concurrency", "INTEGER DEFAULT -1"),
    ("video_concurrency", "INTEGER DEFAULT -1"),
    ("is_expired", "BOOLEAN DEFAULT 0"),
    ("disabled_reason", "TEXT"),
    ("browser_provider", "TEXT"),
    ("browser_profile_id", "TEXT"),
    ("sora_available", "BOOLEAN"),
    ("account_status", "TEXT"),
    ("last_auth_refresh_at", "TIMESTAMP"),
    ("last_auth_result", "TEXT"),
    ("last_auth_error_reason", "TEXT"),
    ("last_challenge_reason", "TEXT"),
    ("last_browser_user_agent", "TEXT"),
    ("last_device_id", "TEXT"),
    ("last_auth_context_hash", "TEXT"),
    ("last_auth_context_expires_at", "TIMESTAMP"),
    ("last_auth_page_url", "TEXT"),
)

TOKEN_TABLE_COLUMN_NAMES = tuple(column_name for column_name, _ in TOKEN_TABLE_COLUMN_DEFINITIONS)

class Database:
    """SQLite database manager"""

    def __init__(self, db_path: str = None):
        if db_path is None:
            # Store database in data directory
            data_dir = Path(__file__).parent.parent.parent / "data"
            data_dir.mkdir(exist_ok=True)
            db_path = str(data_dir / "hancat.db")
        self.db_path = db_path

    def db_exists(self) -> bool:
        """Check if database file exists"""
        return Path(self.db_path).exists()

    def _serialize_token_secret(self, value: Optional[str]) -> Optional[str]:
        return secret_codec.encrypt(value)

    def _deserialize_token_secret(self, value: Optional[str]) -> Optional[str]:
        return secret_codec.decrypt(value)

    def _serialize_polling_context(self, value: Optional[str]) -> Optional[str]:
        return secret_codec.encrypt(value)

    def _deserialize_polling_context(self, value: Optional[str]) -> Optional[str]:
        return secret_codec.decrypt(value)

    def _decode_token_row(self, row: Dict[str, Any]) -> Token:
        payload = dict(row)
        payload["token"] = self._deserialize_token_secret(payload.get("token"))
        payload["st"] = self._deserialize_token_secret(payload.get("st"))
        payload["rt"] = self._deserialize_token_secret(payload.get("rt"))
        return Token(**payload)

    def _decode_task_row(self, row: Dict[str, Any]) -> Task:
        payload = dict(row)
        payload["polling_context"] = self._deserialize_polling_context(payload.get("polling_context"))
        return Task(**payload)

    async def _table_exists(self, db, table_name: str) -> bool:
        """Check if a table exists in the database"""
        cursor = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,)
        )
        result = await cursor.fetchone()
        return result is not None

    async def _get_table_columns(self, db, table_name: str) -> List[str]:
        """Return the current column names for a table."""
        try:
            cursor = await db.execute(f"PRAGMA table_info({table_name})")
            columns = await cursor.fetchall()
            return [col[1] for col in columns]
        except:
            return []

    async def _column_exists(self, db, table_name: str, column_name: str) -> bool:
        """Check if a column exists in a table"""
        return column_name in await self._get_table_columns(db, table_name)

    def _tokens_table_sql(self, table_name: str = "tokens", if_not_exists: bool = True) -> str:
        create_clause = "CREATE TABLE IF NOT EXISTS" if if_not_exists else "CREATE TABLE"
        columns_sql = ",\n                    ".join(
            f"{column_name} {column_type}" for column_name, column_type in TOKEN_TABLE_COLUMN_DEFINITIONS
        )
        return f"""
                {create_clause} {table_name} (
                    {columns_sql}
                )
            """

    async def _rebuild_tokens_table_without_legacy_egress_columns(self, db):
        columns = await self._get_table_columns(db, "tokens")
        if not any(column in columns for column in TOKEN_LEGACY_EGRESS_COLUMNS):
            return

        cleanup_table = "tokens__legacy_cleanup"
        copy_columns_sql = ", ".join(TOKEN_TABLE_COLUMN_NAMES)

        await db.commit()
        await db.execute("PRAGMA foreign_keys = OFF")
        try:
            await db.execute("BEGIN IMMEDIATE")
            try:
                await db.execute(f"DROP TABLE IF EXISTS {cleanup_table}")
                await db.execute(self._tokens_table_sql(cleanup_table, if_not_exists=False))
                await db.execute(
                    f"INSERT INTO {cleanup_table} ({copy_columns_sql}) "
                    f"SELECT {copy_columns_sql} FROM tokens"
                )
                await db.execute("DROP TABLE tokens")
                await db.execute(f"ALTER TABLE {cleanup_table} RENAME TO tokens")
                await db.execute("CREATE INDEX IF NOT EXISTS idx_token_active ON tokens(is_active)")
                await db.commit()
                print("  ✓ Removed legacy token-level egress columns from tokens table")
            except Exception:
                await db.rollback()
                raise
        finally:
            await db.execute("PRAGMA foreign_keys = ON")

    async def _ensure_config_rows(self, db, config_dict: dict = None):
        """Ensure all config tables have their default rows

        Args:
            db: Database connection
            config_dict: Configuration dictionary from setting.toml (optional)
        """
        # Ensure admin_config has a row
        cursor = await db.execute("SELECT COUNT(*) FROM admin_config")
        count = await cursor.fetchone()
        if count[0] == 0:
            # Get admin credentials from config_dict if provided, otherwise use defaults
            admin_username = "admin"
            admin_password = "admin"
            api_key = "han1234"
            error_ban_threshold = 3
            task_retry_enabled = True
            task_max_retries = 3
            auto_disable_on_401 = True

            if config_dict:
                global_config = config_dict.get("global", {})
                admin_username = global_config.get("admin_username", "admin")
                admin_password = global_config.get("admin_password", "admin")
                api_key = global_config.get("api_key", "han1234")

                admin_config = config_dict.get("admin", {})
                error_ban_threshold = admin_config.get("error_ban_threshold", 3)
                task_retry_enabled = admin_config.get("task_retry_enabled", True)
                task_max_retries = admin_config.get("task_max_retries", 3)
                auto_disable_on_401 = admin_config.get("auto_disable_on_401", True)

            await db.execute("""
                INSERT INTO admin_config (id, admin_username, admin_password, api_key, error_ban_threshold, task_retry_enabled, task_max_retries, auto_disable_on_401)
                VALUES (1, ?, ?, ?, ?, ?, ?, ?)
            """, (admin_username, admin_password, api_key, error_ban_threshold, task_retry_enabled, task_max_retries, auto_disable_on_401))

        # Ensure proxy_config has a row
        cursor = await db.execute("SELECT COUNT(*) FROM proxy_config")
        count = await cursor.fetchone()
        if count[0] == 0:
            # Get proxy config from config_dict if provided, otherwise use defaults
            proxy_enabled = False
            proxy_url = None
            image_upload_proxy_enabled = False
            image_upload_proxy_url = None

            if config_dict:
                proxy_config = config_dict.get("proxy", {})
                proxy_enabled = proxy_config.get("proxy_enabled", False)
                proxy_url = proxy_config.get("proxy_url", "")
                image_upload_proxy_enabled = proxy_config.get("image_upload_proxy_enabled", False)
                image_upload_proxy_url = proxy_config.get("image_upload_proxy_url", "")
                # Convert empty string to None
                proxy_url = proxy_url if proxy_url else None
                image_upload_proxy_url = image_upload_proxy_url if image_upload_proxy_url else None

            await db.execute("""
                INSERT INTO proxy_config (
                    id, proxy_enabled, proxy_url, image_upload_proxy_enabled, image_upload_proxy_url
                )
                VALUES (1, ?, ?, ?, ?)
            """, (proxy_enabled, proxy_url, image_upload_proxy_enabled, image_upload_proxy_url))

        # Ensure watermark_free_config has a row
        cursor = await db.execute("SELECT COUNT(*) FROM watermark_free_config")
        count = await cursor.fetchone()
        if count[0] == 0:
            # Get watermark-free config from config_dict if provided, otherwise use defaults
            watermark_free_enabled = False
            parse_method = "third_party"
            custom_parse_url = None
            custom_parse_token = None
            fallback_on_failure = True  # Default to True

            if config_dict:
                watermark_config = config_dict.get("watermark_free", {})
                watermark_free_enabled = watermark_config.get("watermark_free_enabled", False)
                parse_method = watermark_config.get("parse_method", "third_party")
                custom_parse_url = watermark_config.get("custom_parse_url", "")
                custom_parse_token = watermark_config.get("custom_parse_token", "")
                fallback_on_failure = watermark_config.get("fallback_on_failure", True)

                # Convert empty strings to None
                custom_parse_url = custom_parse_url if custom_parse_url else None
                custom_parse_token = custom_parse_token if custom_parse_token else None

            await db.execute("""
                INSERT INTO watermark_free_config (id, watermark_free_enabled, parse_method, custom_parse_url, custom_parse_token, fallback_on_failure)
                VALUES (1, ?, ?, ?, ?, ?)
            """, (watermark_free_enabled, parse_method, custom_parse_url, custom_parse_token, fallback_on_failure))

        # Ensure cache_config has a row
        cursor = await db.execute("SELECT COUNT(*) FROM cache_config")
        count = await cursor.fetchone()
        if count[0] == 0:
            # Get cache config from config_dict if provided, otherwise use defaults
            cache_enabled = False
            cache_timeout = 600
            cache_base_url = None

            if config_dict:
                cache_config = config_dict.get("cache", {})
                cache_enabled = cache_config.get("enabled", False)
                cache_timeout = cache_config.get("timeout", 600)
                cache_base_url = cache_config.get("base_url", "")
                # Convert empty string to None
                cache_base_url = cache_base_url if cache_base_url else None

            await db.execute("""
                INSERT INTO cache_config (id, cache_enabled, cache_timeout, cache_base_url)
                VALUES (1, ?, ?, ?)
            """, (cache_enabled, cache_timeout, cache_base_url))

        # Ensure generation_config has a row
        cursor = await db.execute("SELECT COUNT(*) FROM generation_config")
        count = await cursor.fetchone()
        if count[0] == 0:
            # Get generation config from config_dict if provided, otherwise use defaults
            image_timeout = 300
            video_timeout = 3000

            if config_dict:
                generation_config = config_dict.get("generation", {})
                image_timeout = generation_config.get("image_timeout", 300)
                video_timeout = generation_config.get("video_timeout", 3000)

            await db.execute("""
                INSERT INTO generation_config (id, image_timeout, video_timeout)
                VALUES (1, ?, ?)
            """, (image_timeout, video_timeout))

        # Ensure token_refresh_config has a row
        cursor = await db.execute("SELECT COUNT(*) FROM token_refresh_config")
        count = await cursor.fetchone()
        if count[0] == 0:
            # Get token refresh config from config_dict if provided, otherwise use defaults
            at_auto_refresh_enabled = False

            if config_dict:
                token_refresh_config = config_dict.get("token_refresh", {})
                at_auto_refresh_enabled = token_refresh_config.get("at_auto_refresh_enabled", False)

            await db.execute("""
                INSERT INTO token_refresh_config (id, at_auto_refresh_enabled)
                VALUES (1, ?)
            """, (at_auto_refresh_enabled,))

        # Ensure call_logic_config has a row
        cursor = await db.execute("SELECT COUNT(*) FROM call_logic_config")
        count = await cursor.fetchone()
        if count[0] == 0:
            # Get call logic config from config_dict if provided, otherwise use defaults
            call_mode = "default"
            polling_mode_enabled = False
            poll_interval = 2.5

            if config_dict:
                call_logic_config = config_dict.get("call_logic", {})
                call_mode = call_logic_config.get("call_mode", "default")
                # Normalize call_mode
                if call_mode not in ("default", "polling"):
                    # Check legacy polling_mode_enabled field
                    polling_mode_enabled = call_logic_config.get("polling_mode_enabled", False)
                    call_mode = "polling" if polling_mode_enabled else "default"
                else:
                    polling_mode_enabled = call_mode == "polling"

                sora_config = config_dict.get("sora", {})
                poll_interval = sora_config.get("poll_interval", 2.5)
                if "poll_interval" in call_logic_config:
                    poll_interval = call_logic_config.get("poll_interval", poll_interval)

            try:
                poll_interval = float(poll_interval)
            except (TypeError, ValueError):
                poll_interval = 2.5
            if poll_interval <= 0:
                poll_interval = 2.5

            await db.execute("""
                INSERT INTO call_logic_config (id, call_mode, polling_mode_enabled, poll_interval)
                VALUES (1, ?, ?, ?)
            """, (call_mode, polling_mode_enabled, poll_interval))

        # Ensure pow_proxy_config has a row
        cursor = await db.execute("SELECT COUNT(*) FROM pow_proxy_config")
        count = await cursor.fetchone()
        if count[0] == 0:
            # Get POW proxy config from config_dict if provided, otherwise use defaults
            pow_proxy_enabled = False
            pow_proxy_url = None

            if config_dict:
                pow_proxy_config = config_dict.get("pow_proxy", {})
                pow_proxy_enabled = pow_proxy_config.get("pow_proxy_enabled", False)
                pow_proxy_url = pow_proxy_config.get("pow_proxy_url", "")
                # Convert empty string to None
                pow_proxy_url = pow_proxy_url if pow_proxy_url else None

            await db.execute("""
                INSERT INTO pow_proxy_config (id, pow_proxy_enabled, pow_proxy_url)
                VALUES (1, ?, ?)
            """, (pow_proxy_enabled, pow_proxy_url))

        # Ensure pow_service_config has a row
        cursor = await db.execute("SELECT COUNT(*) FROM pow_service_config")
        count = await cursor.fetchone()
        if count[0] == 0:
            # Get POW service config from config_dict if provided, otherwise use defaults
            mode = "local"
            use_token_for_pow = False
            server_url = None
            api_key = None
            proxy_enabled = False
            proxy_url = None

            if config_dict:
                pow_service_config = config_dict.get("pow_service", {})
                mode = pow_service_config.get("mode", "local")
                use_token_for_pow = pow_service_config.get("use_token_for_pow", False)
                server_url = pow_service_config.get("server_url", "")
                api_key = pow_service_config.get("api_key", "")
                proxy_enabled = pow_service_config.get("proxy_enabled", False)
                proxy_url = pow_service_config.get("proxy_url", "")
                # Convert empty strings to None
                server_url = server_url if server_url else None
                api_key = api_key if api_key else None
                proxy_url = proxy_url if proxy_url else None

            await db.execute("""
                INSERT INTO pow_service_config (id, mode, use_token_for_pow, server_url, api_key, proxy_enabled, proxy_url)
                VALUES (1, ?, ?, ?, ?, ?, ?)
            """, (mode, use_token_for_pow, server_url, api_key, proxy_enabled, proxy_url))


    async def check_and_migrate_db(self, config_dict: dict = None):
        """Check database integrity and perform migrations if needed

        Args:
            config_dict: Configuration dictionary from setting.toml (optional)
                        Used to initialize new tables with values from setting.toml
        """
        async with aiosqlite.connect(self.db_path) as db:
            print("Checking database integrity and performing migrations...")

            # Check and add missing columns to tokens table
            if await self._table_exists(db, "tokens"):
                columns_to_add = [
                    ("sora2_supported", "BOOLEAN"),
                    ("sora2_invite_code", "TEXT"),
                    ("sora2_redeemed_count", "INTEGER DEFAULT 0"),
                    ("sora2_total_count", "INTEGER DEFAULT 0"),
                    ("sora2_remaining_count", "INTEGER DEFAULT 0"),
                    ("sora2_cooldown_until", "TIMESTAMP"),
                    ("image_enabled", "BOOLEAN DEFAULT 1"),
                    ("video_enabled", "BOOLEAN DEFAULT 1"),
                    ("image_concurrency", "INTEGER DEFAULT -1"),
                    ("video_concurrency", "INTEGER DEFAULT -1"),
                    ("client_id", "TEXT"),
                    ("token_hash", "TEXT"),
                    ("proxy_url", "TEXT"),
                    ("is_expired", "BOOLEAN DEFAULT 0"),
                    ("browser_provider", "TEXT"),
                    ("browser_profile_id", "TEXT"),
                    ("sora_available", "BOOLEAN"),
                    ("account_status", "TEXT"),
                    ("last_auth_refresh_at", "TIMESTAMP"),
                    ("last_auth_result", "TEXT"),
                    ("last_auth_error_reason", "TEXT"),
                    ("last_challenge_reason", "TEXT"),
                    ("last_browser_user_agent", "TEXT"),
                    ("last_device_id", "TEXT"),
                    ("last_auth_context_hash", "TEXT"),
                    ("last_auth_context_expires_at", "TIMESTAMP"),
                    ("last_auth_page_url", "TEXT"),
                ]

                for col_name, col_type in columns_to_add:
                    if not await self._column_exists(db, "tokens", col_name):
                        try:
                            await db.execute(f"ALTER TABLE tokens ADD COLUMN {col_name} {col_type}")
                            print(f"  ✓ Added column '{col_name}' to tokens table")
                        except Exception as e:
                            print(f"  ✗ Failed to add column '{col_name}': {e}")

                if await self._column_exists(db, "tokens", "token_hash"):
                    try:
                        cursor = await db.execute("SELECT id, token FROM tokens WHERE token_hash IS NULL")
                        rows = await cursor.fetchall()
                        for token_id, stored_token in rows:
                            try:
                                plain_token = self._deserialize_token_secret(stored_token)
                            except RuntimeError:
                                continue
                            await db.execute(
                                "UPDATE tokens SET token_hash = ? WHERE id = ?",
                                (secret_codec.hash_secret(plain_token), token_id),
                            )
                    except Exception as e:
                        print(f"  ✗ Failed to backfill token_hash: {e}")

                await self._rebuild_tokens_table_without_legacy_egress_columns(db)

            if await self._table_exists(db, "tasks"):
                task_columns_to_add = [
                    ("auth_snapshot_id", "TEXT"),
                    ("polling_context", "TEXT"),
                ]
                for col_name, col_type in task_columns_to_add:
                    if not await self._column_exists(db, "tasks", col_name):
                        try:
                            await db.execute(f"ALTER TABLE tasks ADD COLUMN {col_name} {col_type}")
                            print(f"  ✓ Added column '{col_name}' to tasks table")
                        except Exception as e:
                            print(f"  ✗ Failed to add column '{col_name}': {e}")

            # Check and add missing columns to token_stats table
            if await self._table_exists(db, "token_stats"):
                columns_to_add = [
                    ("consecutive_error_count", "INTEGER DEFAULT 0"),
                ]

                for col_name, col_type in columns_to_add:
                    if not await self._column_exists(db, "token_stats", col_name):
                        try:
                            await db.execute(f"ALTER TABLE token_stats ADD COLUMN {col_name} {col_type}")
                            print(f"  ✓ Added column '{col_name}' to token_stats table")
                        except Exception as e:
                            print(f"  ✗ Failed to add column '{col_name}': {e}")

            # Check and add missing columns to admin_config table
            if await self._table_exists(db, "admin_config"):
                columns_to_add = [
                    ("admin_username", "TEXT DEFAULT 'admin'"),
                    ("admin_password", "TEXT DEFAULT 'admin'"),
                    ("api_key", "TEXT DEFAULT 'han1234'"),
                ]

                for col_name, col_type in columns_to_add:
                    if not await self._column_exists(db, "admin_config", col_name):
                        try:
                            await db.execute(f"ALTER TABLE admin_config ADD COLUMN {col_name} {col_type}")
                            print(f"  ✓ Added column '{col_name}' to admin_config table")
                        except Exception as e:
                            print(f"  ✗ Failed to add column '{col_name}': {e}")

            # Check and add missing columns to proxy_config table
            if await self._table_exists(db, "proxy_config"):
                added_image_upload_proxy_enabled_column = False
                added_image_upload_proxy_url_column = False
                columns_to_add = [
                    ("image_upload_proxy_enabled", "BOOLEAN DEFAULT 0"),
                    ("image_upload_proxy_url", "TEXT"),
                ]

                for col_name, col_type in columns_to_add:
                    if not await self._column_exists(db, "proxy_config", col_name):
                        try:
                            await db.execute(f"ALTER TABLE proxy_config ADD COLUMN {col_name} {col_type}")
                            print(f"  ✓ Added column '{col_name}' to proxy_config table")
                            if col_name == "image_upload_proxy_enabled":
                                added_image_upload_proxy_enabled_column = True
                            if col_name == "image_upload_proxy_url":
                                added_image_upload_proxy_url_column = True
                        except Exception as e:
                            print(f"  ✗ Failed to add column '{col_name}': {e}")

                # On upgrade, initialize value from setting.toml only when columns are newly added
                if config_dict and (added_image_upload_proxy_enabled_column or added_image_upload_proxy_url_column):
                    try:
                        proxy_config = config_dict.get("proxy", {})
                        image_upload_proxy_enabled = proxy_config.get("image_upload_proxy_enabled", False)
                        image_upload_proxy_url = proxy_config.get("image_upload_proxy_url", "")
                        image_upload_proxy_url = image_upload_proxy_url if image_upload_proxy_url else None
                        await db.execute("""
                            UPDATE proxy_config
                            SET image_upload_proxy_enabled = ?, image_upload_proxy_url = ?
                            WHERE id = 1
                        """, (image_upload_proxy_enabled, image_upload_proxy_url))
                    except Exception as e:
                        print(f"  ✗ Failed to initialize image upload proxy config from config: {e}")

            # Check and add missing columns to pow_service_config table
            if await self._table_exists(db, "pow_service_config"):
                added_use_token_for_pow_column = False
                columns_to_add = [
                    ("use_token_for_pow", "BOOLEAN DEFAULT 0"),
                ]

                for col_name, col_type in columns_to_add:
                    if not await self._column_exists(db, "pow_service_config", col_name):
                        try:
                            await db.execute(f"ALTER TABLE pow_service_config ADD COLUMN {col_name} {col_type}")
                            print(f"  ✓ Added column '{col_name}' to pow_service_config table")
                            if col_name == "use_token_for_pow":
                                added_use_token_for_pow_column = True
                        except Exception as e:
                            print(f"  ✗ Failed to add column '{col_name}': {e}")

                # On upgrade, initialize value from setting.toml only when this column is newly added
                if config_dict and added_use_token_for_pow_column:
                    try:
                        use_token_for_pow = config_dict.get("pow_service", {}).get("use_token_for_pow", False)
                        await db.execute("""
                            UPDATE pow_service_config
                            SET use_token_for_pow = ?
                            WHERE id = 1
                        """, (use_token_for_pow,))
                    except Exception as e:
                        print(f"  ✗ Failed to initialize use_token_for_pow from config: {e}")

            # Check and add missing columns to call_logic_config table
            if await self._table_exists(db, "call_logic_config"):
                added_poll_interval_column = False
                columns_to_add = [
                    ("poll_interval", "REAL DEFAULT 2.5"),
                ]

                for col_name, col_type in columns_to_add:
                    if not await self._column_exists(db, "call_logic_config", col_name):
                        try:
                            await db.execute(f"ALTER TABLE call_logic_config ADD COLUMN {col_name} {col_type}")
                            print(f"  ✓ Added column '{col_name}' to call_logic_config table")
                            if col_name == "poll_interval":
                                added_poll_interval_column = True
                        except Exception as e:
                            print(f"  ✗ Failed to add column '{col_name}': {e}")

                # On upgrade, initialize value from setting.toml only when this column is newly added
                if config_dict and added_poll_interval_column:
                    try:
                        poll_interval = config_dict.get("sora", {}).get("poll_interval", 2.5)
                        poll_interval = float(poll_interval)
                        if poll_interval <= 0:
                            poll_interval = 2.5
                        await db.execute("""
                            UPDATE call_logic_config
                            SET poll_interval = ?
                            WHERE id = 1
                        """, (poll_interval,))
                    except Exception as e:
                        print(f"  ✗ Failed to initialize poll_interval from config: {e}")

            # Check and add missing columns to watermark_free_config table
            if await self._table_exists(db, "watermark_free_config"):
                columns_to_add = [
                    ("parse_method", "TEXT DEFAULT 'third_party'"),
                    ("custom_parse_url", "TEXT"),
                    ("custom_parse_token", "TEXT"),
                    ("fallback_on_failure", "BOOLEAN DEFAULT 1"),
                ]

                for col_name, col_type in columns_to_add:
                    if not await self._column_exists(db, "watermark_free_config", col_name):
                        try:
                            await db.execute(f"ALTER TABLE watermark_free_config ADD COLUMN {col_name} {col_type}")
                            print(f"  ✓ Added column '{col_name}' to watermark_free_config table")
                        except Exception as e:
                            print(f"  ✗ Failed to add column '{col_name}': {e}")

            # Check and add missing columns to request_logs table
            if await self._table_exists(db, "request_logs"):
                columns_to_add = [
                    ("task_id", "TEXT"),
                    ("updated_at", "TIMESTAMP"),
                    ("stage", "TEXT"),
                    ("trigger_source", "TEXT"),
                    ("is_redacted", "BOOLEAN DEFAULT 1"),
                ]

                for col_name, col_type in columns_to_add:
                    if not await self._column_exists(db, "request_logs", col_name):
                        try:
                            await db.execute(f"ALTER TABLE request_logs ADD COLUMN {col_name} {col_type}")
                            print(f"  ✓ Added column '{col_name}' to request_logs table")
                        except Exception as e:
                            print(f"  ✗ Failed to add column '{col_name}': {e}")

            if await self._table_exists(db, "tasks"):
                columns_to_add = [
                    ("current_stage", "TEXT"),
                    ("failure_stage", "TEXT"),
                    ("error_code", "TEXT"),
                    ("error_category", "TEXT"),
                    ("last_event_at", "TIMESTAMP"),
                ]

                for col_name, col_type in columns_to_add:
                    if not await self._column_exists(db, "tasks", col_name):
                        try:
                            await db.execute(f"ALTER TABLE tasks ADD COLUMN {col_name} {col_type}")
                            print(f"  ✓ Added column '{col_name}' to tasks table")
                        except Exception as e:
                            print(f"  ✗ Failed to add column '{col_name}': {e}")

            await db.execute("""
                CREATE TABLE IF NOT EXISTS mutation_attempts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    token_id INTEGER,
                    task_id TEXT,
                    mutation_type TEXT NOT NULL,
                    strategy TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'started',
                    provider TEXT,
                    profile_id TEXT,
                    window_id TEXT,
                    page_url TEXT,
                    egress_binding TEXT,
                    details TEXT,
                    error_code TEXT,
                    error_reason TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (token_id) REFERENCES tokens(id)
                )
            """)

            await db.execute("""
                CREATE TABLE IF NOT EXISTS task_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT,
                    token_id INTEGER,
                    event_type TEXT NOT NULL,
                    stage TEXT,
                    status TEXT NOT NULL DEFAULT 'info',
                    message TEXT,
                    details TEXT,
                    error_code TEXT,
                    error_reason TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (token_id) REFERENCES tokens(id)
                )
            """)

            await db.execute("""
                CREATE TABLE IF NOT EXISTS error_attributions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT,
                    token_id INTEGER,
                    mutation_type TEXT,
                    stage TEXT NOT NULL,
                    error_code TEXT,
                    error_reason TEXT,
                    details TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (token_id) REFERENCES tokens(id)
                )
            """)

            # Ensure all config tables have their default rows
            # Pass config_dict if available to initialize from setting.toml
            await self._ensure_config_rows(db, config_dict)

            await db.commit()
            print("Database migration check completed.")

    async def init_db(self, config_dict: dict = None):
        """Initialize database tables - creates all tables and ensures data integrity

        Args:
            config_dict: Configuration dictionary from setting.toml (optional).
                        Used to initialize newly-added proxy columns during migration.
        """
        async with aiosqlite.connect(self.db_path) as db:
            # Tokens table
            await db.execute(self._tokens_table_sql())

            # Token stats table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS token_stats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    token_id INTEGER NOT NULL,
                    image_count INTEGER DEFAULT 0,
                    video_count INTEGER DEFAULT 0,
                    error_count INTEGER DEFAULT 0,
                    last_error_at TIMESTAMP,
                    today_image_count INTEGER DEFAULT 0,
                    today_video_count INTEGER DEFAULT 0,
                    today_error_count INTEGER DEFAULT 0,
                    today_date DATE,
                    consecutive_error_count INTEGER DEFAULT 0,
                    FOREIGN KEY (token_id) REFERENCES tokens(id)
                )
            """)

            # Tasks table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT UNIQUE NOT NULL,
                    token_id INTEGER NOT NULL,
                    model TEXT NOT NULL,
                    prompt TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'processing',
                    progress FLOAT DEFAULT 0,
                    result_urls TEXT,
                    error_message TEXT,
                    current_stage TEXT,
                    failure_stage TEXT,
                    error_code TEXT,
                    error_category TEXT,
                    auth_snapshot_id TEXT,
                    polling_context TEXT,
                    last_event_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    completed_at TIMESTAMP,
                    FOREIGN KEY (token_id) REFERENCES tokens(id)
                )
            """)

            # Request logs table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS request_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    token_id INTEGER,
                    task_id TEXT,
                    operation TEXT NOT NULL,
                    request_body TEXT,
                    response_body TEXT,
                    stage TEXT,
                    trigger_source TEXT,
                    is_redacted BOOLEAN DEFAULT 1,
                    status_code INTEGER NOT NULL,
                    duration FLOAT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP,
                    FOREIGN KEY (token_id) REFERENCES tokens(id)
                )
            """)

            await db.execute("""
                CREATE TABLE IF NOT EXISTS mutation_attempts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    token_id INTEGER,
                    task_id TEXT,
                    mutation_type TEXT NOT NULL,
                    strategy TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'started',
                    provider TEXT,
                    profile_id TEXT,
                    window_id TEXT,
                    page_url TEXT,
                    egress_binding TEXT,
                    details TEXT,
                    error_code TEXT,
                    error_reason TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (token_id) REFERENCES tokens(id)
                )
            """)

            await db.execute("""
                CREATE TABLE IF NOT EXISTS task_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT,
                    token_id INTEGER,
                    event_type TEXT NOT NULL,
                    stage TEXT,
                    status TEXT NOT NULL DEFAULT 'info',
                    message TEXT,
                    details TEXT,
                    error_code TEXT,
                    error_reason TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (token_id) REFERENCES tokens(id)
                )
            """)

            await db.execute("""
                CREATE TABLE IF NOT EXISTS error_attributions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT,
                    token_id INTEGER,
                    mutation_type TEXT,
                    stage TEXT NOT NULL,
                    error_code TEXT,
                    error_reason TEXT,
                    details TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (token_id) REFERENCES tokens(id)
                )
            """)

            # Admin config table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS admin_config (
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

            # Proxy config table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS proxy_config (
                    id INTEGER PRIMARY KEY DEFAULT 1,
                    proxy_enabled BOOLEAN DEFAULT 0,
                    proxy_url TEXT,
                    image_upload_proxy_enabled BOOLEAN DEFAULT 0,
                    image_upload_proxy_url TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Watermark-free config table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS watermark_free_config (
                    id INTEGER PRIMARY KEY DEFAULT 1,
                    watermark_free_enabled BOOLEAN DEFAULT 0,
                    parse_method TEXT DEFAULT 'third_party',
                    custom_parse_url TEXT,
                    custom_parse_token TEXT,
                    fallback_on_failure BOOLEAN DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Cache config table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS cache_config (
                    id INTEGER PRIMARY KEY DEFAULT 1,
                    cache_enabled BOOLEAN DEFAULT 0,
                    cache_timeout INTEGER DEFAULT 600,
                    cache_base_url TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Generation config table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS generation_config (
                    id INTEGER PRIMARY KEY DEFAULT 1,
                    image_timeout INTEGER DEFAULT 300,
                    video_timeout INTEGER DEFAULT 3000,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Token refresh config table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS token_refresh_config (
                    id INTEGER PRIMARY KEY DEFAULT 1,
                    at_auto_refresh_enabled BOOLEAN DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Call logic config table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS call_logic_config (
                    id INTEGER PRIMARY KEY DEFAULT 1,
                    call_mode TEXT DEFAULT 'default',
                    polling_mode_enabled BOOLEAN DEFAULT 0,
                    poll_interval REAL DEFAULT 2.5,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # POW proxy config table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS pow_proxy_config (
                    id INTEGER PRIMARY KEY DEFAULT 1,
                    pow_proxy_enabled BOOLEAN DEFAULT 0,
                    pow_proxy_url TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Create pow_service_config table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS pow_service_config (
                    id INTEGER PRIMARY KEY DEFAULT 1,
                    mode TEXT DEFAULT 'local',
                    use_token_for_pow BOOLEAN DEFAULT 0,
                    server_url TEXT,
                    api_key TEXT,
                    proxy_enabled BOOLEAN DEFAULT 0,
                    proxy_url TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Create indexes
            await db.execute("CREATE INDEX IF NOT EXISTS idx_task_id ON tasks(task_id)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_task_status ON tasks(status)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_token_active ON tokens(is_active)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_mutation_attempts_token ON mutation_attempts(token_id)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_mutation_attempts_task ON mutation_attempts(task_id)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_task_events_task ON task_events(task_id)")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_error_attributions_task ON error_attributions(task_id)")

            # Migration: Add daily statistics columns if they don't exist
            if not await self._column_exists(db, "token_stats", "today_image_count"):
                await db.execute("ALTER TABLE token_stats ADD COLUMN today_image_count INTEGER DEFAULT 0")
            if not await self._column_exists(db, "token_stats", "today_video_count"):
                await db.execute("ALTER TABLE token_stats ADD COLUMN today_video_count INTEGER DEFAULT 0")
            if not await self._column_exists(db, "token_stats", "today_error_count"):
                await db.execute("ALTER TABLE token_stats ADD COLUMN today_error_count INTEGER DEFAULT 0")
            if not await self._column_exists(db, "token_stats", "today_date"):
                await db.execute("ALTER TABLE token_stats ADD COLUMN today_date DATE")

            # Migration: Add retry_count column to tasks table if it doesn't exist
            if not await self._column_exists(db, "tasks", "retry_count"):
                await db.execute("ALTER TABLE tasks ADD COLUMN retry_count INTEGER DEFAULT 0")

            # Migration: Add task retry config columns to admin_config table if they don't exist
            if not await self._column_exists(db, "admin_config", "task_retry_enabled"):
                await db.execute("ALTER TABLE admin_config ADD COLUMN task_retry_enabled BOOLEAN DEFAULT 1")
            if not await self._column_exists(db, "admin_config", "task_max_retries"):
                await db.execute("ALTER TABLE admin_config ADD COLUMN task_max_retries INTEGER DEFAULT 3")
            if not await self._column_exists(db, "admin_config", "auto_disable_on_401"):
                await db.execute("ALTER TABLE admin_config ADD COLUMN auto_disable_on_401 BOOLEAN DEFAULT 1")

            # Migration: Add image upload proxy columns to proxy_config table if they don't exist
            added_image_upload_proxy_enabled_column = False
            added_image_upload_proxy_url_column = False
            if not await self._column_exists(db, "proxy_config", "image_upload_proxy_enabled"):
                await db.execute("ALTER TABLE proxy_config ADD COLUMN image_upload_proxy_enabled BOOLEAN DEFAULT 0")
                added_image_upload_proxy_enabled_column = True
            if not await self._column_exists(db, "proxy_config", "image_upload_proxy_url"):
                await db.execute("ALTER TABLE proxy_config ADD COLUMN image_upload_proxy_url TEXT")
                added_image_upload_proxy_url_column = True

            # If migration added image upload proxy columns, initialize them from setting.toml defaults
            if config_dict and (added_image_upload_proxy_enabled_column or added_image_upload_proxy_url_column):
                proxy_config = config_dict.get("proxy", {})
                image_upload_proxy_enabled = proxy_config.get("image_upload_proxy_enabled", False)
                image_upload_proxy_url = proxy_config.get("image_upload_proxy_url", "")
                image_upload_proxy_url = image_upload_proxy_url if image_upload_proxy_url else None
                await db.execute("""
                    UPDATE proxy_config
                    SET image_upload_proxy_enabled = ?, image_upload_proxy_url = ?
                    WHERE id = 1
                """, (image_upload_proxy_enabled, image_upload_proxy_url))

            # Migration: Add disabled_reason column to tokens table if it doesn't exist
            if not await self._column_exists(db, "tokens", "disabled_reason"):
                await db.execute("ALTER TABLE tokens ADD COLUMN disabled_reason TEXT")
                # For existing disabled tokens without a reason, set to 'manual'
                await db.execute("""
                    UPDATE tokens
                    SET disabled_reason = 'manual'
                    WHERE is_active = 0 AND disabled_reason IS NULL
                """)
                # For existing expired tokens, set to 'expired'
                await db.execute("""
                    UPDATE tokens
                    SET disabled_reason = 'expired'
                    WHERE is_expired = 1 AND disabled_reason IS NULL
                """)

            await db.commit()

    async def init_config_from_toml(self, config_dict: dict, is_first_startup: bool = True):
        """
        Initialize database configuration from setting.toml

        Args:
            config_dict: Configuration dictionary from setting.toml
            is_first_startup: If True, initialize all config rows from setting.toml.
                            If False (upgrade mode), only ensure missing config rows exist with default values.
        """
        async with aiosqlite.connect(self.db_path) as db:
            if is_first_startup:
                # First startup: Initialize all config tables with values from setting.toml
                await self._ensure_config_rows(db, config_dict)
            else:
                # Upgrade mode: Only ensure missing config rows exist (with default values, not from TOML)
                await self._ensure_config_rows(db, config_dict=None)

            await db.commit()

    # Token operations
    async def add_token(self, token: Token) -> int:
        """Add a new token"""
        async with aiosqlite.connect(self.db_path) as db:
            token_payload = {
                "token": self._serialize_token_secret(token.token),
                "token_hash": secret_codec.hash_secret(token.token),
                "email": token.email,
                "username": "",
                "name": token.name,
                "st": self._serialize_token_secret(token.st),
                "rt": self._serialize_token_secret(token.rt),
                "client_id": token.client_id,
                "proxy_url": token.proxy_url,
                "remark": token.remark,
                "expiry_time": token.expiry_time,
                "is_active": token.is_active,
                "plan_type": token.plan_type,
                "plan_title": token.plan_title,
                "subscription_end": token.subscription_end,
                "sora2_supported": token.sora2_supported,
                "sora2_invite_code": token.sora2_invite_code,
                "sora2_redeemed_count": token.sora2_redeemed_count,
                "sora2_total_count": token.sora2_total_count,
                "sora2_remaining_count": token.sora2_remaining_count,
                "sora2_cooldown_until": token.sora2_cooldown_until,
                "image_enabled": token.image_enabled,
                "video_enabled": token.video_enabled,
                "image_concurrency": token.image_concurrency,
                "video_concurrency": token.video_concurrency,
                "browser_provider": token.browser_provider,
                "browser_profile_id": token.browser_profile_id,
                "sora_available": token.sora_available,
                "account_status": token.account_status,
                "last_auth_refresh_at": token.last_auth_refresh_at,
                "last_auth_result": token.last_auth_result,
                "last_auth_error_reason": token.last_auth_error_reason,
                "last_challenge_reason": token.last_challenge_reason,
                "last_browser_user_agent": token.last_browser_user_agent,
                "last_device_id": token.last_device_id,
                "last_auth_context_hash": token.last_auth_context_hash,
                "last_auth_context_expires_at": token.last_auth_context_expires_at,
                "last_auth_page_url": token.last_auth_page_url,
            }
            columns_sql = ", ".join(token_payload.keys())
            placeholders = ", ".join("?" for _ in token_payload)
            cursor = await db.execute(
                f"INSERT INTO tokens ({columns_sql}) VALUES ({placeholders})",
                tuple(token_payload.values()),
            )
            await db.commit()
            token_id = cursor.lastrowid

            # Create stats entry
            await db.execute("""
                INSERT INTO token_stats (token_id) VALUES (?)
            """, (token_id,))
            await db.commit()

            return token_id
    
    async def get_token(self, token_id: int) -> Optional[Token]:
        """Get token by ID"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM tokens WHERE id = ?", (token_id,))
            row = await cursor.fetchone()
            if row:
                return self._decode_token_row(dict(row))
            return None
    
    async def get_token_by_value(self, token: str) -> Optional[Token]:
        """Get token by value"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM tokens WHERE token_hash = ? OR token = ?",
                (secret_codec.hash_secret(token), token),
            )
            row = await cursor.fetchone()
            if row:
                return self._decode_token_row(dict(row))
            return None

    async def get_token_by_email(self, email: str) -> Optional[Token]:
        """Get token by email"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM tokens WHERE email = ?", (email,))
            row = await cursor.fetchone()
            if row:
                return self._decode_token_row(dict(row))
            return None
    
    async def get_active_tokens(self) -> List[Token]:
        """Get all active tokens (enabled, not cooled down, not expired)"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("""
                SELECT * FROM tokens
                WHERE is_active = 1
                AND (cooled_until IS NULL OR cooled_until < CURRENT_TIMESTAMP)
                AND expiry_time > CURRENT_TIMESTAMP
                ORDER BY last_used_at ASC NULLS FIRST
            """)
            rows = await cursor.fetchall()
            return [self._decode_token_row(dict(row)) for row in rows]
    
    async def get_all_tokens(self) -> List[Token]:
        """Get all tokens"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM tokens ORDER BY created_at DESC")
            rows = await cursor.fetchall()
            return [self._decode_token_row(dict(row)) for row in rows]

    async def count_active_tokens(self) -> int:
        """Count active tokens eligible for selection."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("""
                SELECT COUNT(*) FROM tokens
                WHERE is_active = 1
                AND (cooled_until IS NULL OR cooled_until < CURRENT_TIMESTAMP)
                AND expiry_time > CURRENT_TIMESTAMP
            """)
            row = await cursor.fetchone()
            return int(row[0] if row else 0)
    
    async def update_token_usage(self, token_id: int):
        """Update token usage"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                UPDATE tokens 
                SET last_used_at = CURRENT_TIMESTAMP, use_count = use_count + 1
                WHERE id = ?
            """, (token_id,))
            await db.commit()
    
    async def update_token_status(self, token_id: int, is_active: bool, disabled_reason: Optional[str] = None):
        """Update token status and disabled reason"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                UPDATE tokens SET is_active = ?, disabled_reason = ? WHERE id = ?
            """, (is_active, disabled_reason, token_id))
            await db.commit()

    async def mark_token_expired(self, token_id: int):
        """Mark token as expired and disable it with reason"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                UPDATE tokens SET is_expired = 1, is_active = 0, disabled_reason = ? WHERE id = ?
            """, ("expired", token_id))
            await db.commit()

    async def mark_token_invalid(self, token_id: int):
        """Mark token as invalid (401 error) and disable it"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                UPDATE tokens SET is_expired = 1, is_active = 0, disabled_reason = ? WHERE id = ?
            """, ("token_invalid", token_id))
            await db.commit()

    async def clear_token_expired(self, token_id: int):
        """Clear token expired flag and disabled reason"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                UPDATE tokens SET is_expired = 0, disabled_reason = NULL WHERE id = ?
            """, (token_id,))
            await db.commit()

    async def update_token_sora2(self, token_id: int, supported: bool, invite_code: Optional[str] = None,
                                redeemed_count: int = 0, total_count: int = 0, remaining_count: int = 0):
        """Update token Sora2 support info"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                UPDATE tokens
                SET sora2_supported = ?, sora2_invite_code = ?, sora2_redeemed_count = ?, sora2_total_count = ?, sora2_remaining_count = ?
                WHERE id = ?
            """, (supported, invite_code, redeemed_count, total_count, remaining_count, token_id))
            await db.commit()

    async def update_token_sora2_remaining(self, token_id: int, remaining_count: int):
        """Update token Sora2 remaining count"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                UPDATE tokens SET sora2_remaining_count = ? WHERE id = ?
            """, (remaining_count, token_id))
            await db.commit()

    async def update_token_sora2_cooldown(self, token_id: int, cooldown_until: Optional[datetime]):
        """Update token Sora2 cooldown time"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                UPDATE tokens SET sora2_cooldown_until = ? WHERE id = ?
            """, (cooldown_until, token_id))
            await db.commit()

    async def update_token_cooldown(self, token_id: int, cooled_until: datetime):
        """Update token cooldown"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                UPDATE tokens SET cooled_until = ? WHERE id = ?
            """, (cooled_until, token_id))
            await db.commit()
    
    async def delete_token(self, token_id: int):
        """Delete token"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM token_stats WHERE token_id = ?", (token_id,))
            await db.execute("DELETE FROM tokens WHERE id = ?", (token_id,))
            await db.commit()

    async def update_token(self, token_id: int,
                          token: Optional[str] = None,
                          st: Optional[str] = None,
                          rt: Optional[str] = None,
                          client_id: Optional[str] = None,
                          proxy_url: Optional[str] = None,
                          remark: Optional[str] = None,
                          expiry_time: Optional[datetime] = None,
                          plan_type: Optional[str] = None,
                          plan_title: Optional[str] = None,
                          subscription_end: Optional[datetime] = None,
                          image_enabled: Optional[bool] = None,
                          video_enabled: Optional[bool] = None,
                          image_concurrency: Optional[int] = None,
                          video_concurrency: Optional[int] = None,
                          browser_provider: Optional[str] = None,
                          browser_profile_id: Optional[str] = None,
                          sora_available: Optional[bool] = None,
                          account_status: Optional[str] = None,
                          last_auth_refresh_at: Optional[datetime] = None,
                          last_auth_result: Optional[str] = None,
                          last_auth_error_reason: Optional[str] = None,
                          last_challenge_reason: Optional[str] = None,
                          last_browser_user_agent: Optional[str] = None,
                          last_device_id: Optional[str] = None,
                          last_auth_context_hash: Optional[str] = None,
                          last_auth_context_expires_at: Optional[datetime] = None,
                          last_auth_page_url: Optional[str] = None):
        """Update token (AT, ST, RT, client_id, proxy_url, remark, expiry_time, subscription info, image_enabled, video_enabled)"""
        async with aiosqlite.connect(self.db_path) as db:
            # Build dynamic update query
            updates = []
            params = []

            if token is not None:
                updates.append("token = ?")
                params.append(self._serialize_token_secret(token))
                updates.append("token_hash = ?")
                params.append(secret_codec.hash_secret(token))

            if st is not None:
                updates.append("st = ?")
                params.append(self._serialize_token_secret(st))

            if rt is not None:
                updates.append("rt = ?")
                params.append(self._serialize_token_secret(rt))

            if client_id is not None:
                updates.append("client_id = ?")
                params.append(client_id)

            if proxy_url is not None:
                updates.append("proxy_url = ?")
                params.append(proxy_url)

            if remark is not None:
                updates.append("remark = ?")
                params.append(remark)

            if expiry_time is not None:
                updates.append("expiry_time = ?")
                params.append(expiry_time)

            if plan_type is not None:
                updates.append("plan_type = ?")
                params.append(plan_type)

            if plan_title is not None:
                updates.append("plan_title = ?")
                params.append(plan_title)

            if subscription_end is not None:
                updates.append("subscription_end = ?")
                params.append(subscription_end)

            if image_enabled is not None:
                updates.append("image_enabled = ?")
                params.append(image_enabled)

            if video_enabled is not None:
                updates.append("video_enabled = ?")
                params.append(video_enabled)

            if image_concurrency is not None:
                updates.append("image_concurrency = ?")
                params.append(image_concurrency)

            if video_concurrency is not None:
                updates.append("video_concurrency = ?")
                params.append(video_concurrency)

            if browser_provider is not None:
                updates.append("browser_provider = ?")
                params.append(browser_provider)

            if browser_profile_id is not None:
                updates.append("browser_profile_id = ?")
                params.append(browser_profile_id)

            if sora_available is not None:
                updates.append("sora_available = ?")
                params.append(sora_available)

            if account_status is not None:
                updates.append("account_status = ?")
                params.append(account_status)

            if last_auth_refresh_at is not None:
                updates.append("last_auth_refresh_at = ?")
                params.append(last_auth_refresh_at)

            if last_auth_result is not None:
                updates.append("last_auth_result = ?")
                params.append(last_auth_result)

            if last_auth_error_reason is not None:
                updates.append("last_auth_error_reason = ?")
                params.append(last_auth_error_reason)

            if last_challenge_reason is not None:
                updates.append("last_challenge_reason = ?")
                params.append(last_challenge_reason)

            if last_browser_user_agent is not None:
                updates.append("last_browser_user_agent = ?")
                params.append(last_browser_user_agent)

            if last_device_id is not None:
                updates.append("last_device_id = ?")
                params.append(last_device_id)

            if last_auth_context_hash is not None:
                updates.append("last_auth_context_hash = ?")
                params.append(last_auth_context_hash)

            if last_auth_context_expires_at is not None:
                updates.append("last_auth_context_expires_at = ?")
                params.append(last_auth_context_expires_at)

            if last_auth_page_url is not None:
                updates.append("last_auth_page_url = ?")
                params.append(last_auth_page_url)

            if updates:
                params.append(token_id)
                query = f"UPDATE tokens SET {', '.join(updates)} WHERE id = ?"
                await db.execute(query, params)
                await db.commit()

    # Token stats operations
    async def get_token_stats(self, token_id: int) -> Optional[TokenStats]:
        """Get token statistics"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM token_stats WHERE token_id = ?", (token_id,))
            row = await cursor.fetchone()
            if row:
                return TokenStats(**dict(row))
            return None
    
    async def increment_image_count(self, token_id: int):
        """Increment image generation count"""
        from datetime import date
        async with aiosqlite.connect(self.db_path) as db:
            today = str(date.today())
            # Get current stats
            cursor = await db.execute("SELECT today_date FROM token_stats WHERE token_id = ?", (token_id,))
            row = await cursor.fetchone()

            # If date changed, reset today's count
            if row and row[0] != today:
                await db.execute("""
                    UPDATE token_stats
                    SET image_count = image_count + 1,
                        today_image_count = 1,
                        today_date = ?
                    WHERE token_id = ?
                """, (today, token_id))
            else:
                # Same day, just increment both
                await db.execute("""
                    UPDATE token_stats
                    SET image_count = image_count + 1,
                        today_image_count = today_image_count + 1,
                        today_date = ?
                    WHERE token_id = ?
                """, (today, token_id))
            await db.commit()

    async def increment_video_count(self, token_id: int):
        """Increment video generation count"""
        from datetime import date
        async with aiosqlite.connect(self.db_path) as db:
            today = str(date.today())
            # Get current stats
            cursor = await db.execute("SELECT today_date FROM token_stats WHERE token_id = ?", (token_id,))
            row = await cursor.fetchone()

            # If date changed, reset today's count
            if row and row[0] != today:
                await db.execute("""
                    UPDATE token_stats
                    SET video_count = video_count + 1,
                        today_video_count = 1,
                        today_date = ?
                    WHERE token_id = ?
                """, (today, token_id))
            else:
                # Same day, just increment both
                await db.execute("""
                    UPDATE token_stats
                    SET video_count = video_count + 1,
                        today_video_count = today_video_count + 1,
                        today_date = ?
                    WHERE token_id = ?
                """, (today, token_id))
            await db.commit()
    
    async def increment_error_count(self, token_id: int, increment_consecutive: bool = True):
        """Increment error count

        Args:
            token_id: Token ID
            increment_consecutive: Whether to increment consecutive error count (False for overload errors)
        """
        from datetime import date
        async with aiosqlite.connect(self.db_path) as db:
            today = str(date.today())
            # Get current stats
            cursor = await db.execute("SELECT today_date FROM token_stats WHERE token_id = ?", (token_id,))
            row = await cursor.fetchone()

            # If date changed, reset today's error count
            if row and row[0] != today:
                if increment_consecutive:
                    await db.execute("""
                        UPDATE token_stats
                        SET error_count = error_count + 1,
                            consecutive_error_count = consecutive_error_count + 1,
                            today_error_count = 1,
                            today_date = ?,
                            last_error_at = CURRENT_TIMESTAMP
                        WHERE token_id = ?
                    """, (today, token_id))
                else:
                    await db.execute("""
                        UPDATE token_stats
                        SET error_count = error_count + 1,
                            today_error_count = 1,
                            today_date = ?,
                            last_error_at = CURRENT_TIMESTAMP
                        WHERE token_id = ?
                    """, (today, token_id))
            else:
                # Same day, just increment counters
                if increment_consecutive:
                    await db.execute("""
                        UPDATE token_stats
                        SET error_count = error_count + 1,
                            consecutive_error_count = consecutive_error_count + 1,
                            today_error_count = today_error_count + 1,
                            today_date = ?,
                            last_error_at = CURRENT_TIMESTAMP
                        WHERE token_id = ?
                    """, (today, token_id))
                else:
                    await db.execute("""
                        UPDATE token_stats
                        SET error_count = error_count + 1,
                            today_error_count = today_error_count + 1,
                            today_date = ?,
                            last_error_at = CURRENT_TIMESTAMP
                        WHERE token_id = ?
                    """, (today, token_id))
            await db.commit()
    
    async def reset_error_count(self, token_id: int):
        """Reset consecutive error count (keep total error_count)"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                UPDATE token_stats SET consecutive_error_count = 0 WHERE token_id = ?
            """, (token_id,))
            await db.commit()
    
    # Task operations
    async def create_task(self, task: Task) -> int:
        """Create a new task"""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("""
                INSERT INTO tasks (
                    task_id, token_id, model, prompt, status, progress,
                    current_stage, failure_stage, error_code, error_category,
                    auth_snapshot_id, polling_context, last_event_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                task.task_id,
                task.token_id,
                task.model,
                task.prompt,
                task.status,
                task.progress,
                task.current_stage,
                task.failure_stage,
                task.error_code,
                task.error_category,
                task.auth_snapshot_id,
                self._serialize_polling_context(task.polling_context),
                task.last_event_at,
            ))
            await db.commit()
            return cursor.lastrowid

    async def update_task(self, task_id: str, status: str, progress: float,
                         result_urls: Optional[str] = None, error_message: Optional[str] = None,
                         current_stage: Optional[str] = None):
        """Update task status"""
        async with aiosqlite.connect(self.db_path) as db:
            completed_at = datetime.now() if status in ["completed", "failed"] else None
            effective_stage = current_stage
            if status == "completed":
                effective_stage = "completed"
            await db.execute("""
                UPDATE tasks 
                SET status = ?, progress = ?, result_urls = ?, error_message = ?, completed_at = ?,
                    current_stage = COALESCE(?, current_stage),
                    last_event_at = CURRENT_TIMESTAMP
                WHERE task_id = ?
            """, (status, progress, result_urls, error_message, completed_at, effective_stage, task_id))
            await db.commit()

    async def update_task_polling_context(
        self,
        task_id: str,
        polling_context: Optional[str],
        auth_snapshot_id: Optional[str] = None,
    ):
        """Persist task-scoped polling context."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                UPDATE tasks
                SET polling_context = ?, auth_snapshot_id = COALESCE(?, auth_snapshot_id),
                    last_event_at = CURRENT_TIMESTAMP
                WHERE task_id = ?
            """, (self._serialize_polling_context(polling_context), auth_snapshot_id, task_id))
            await db.commit()

    async def update_task_stage(
        self,
        task_id: str,
        current_stage: Optional[str] = None,
        failure_stage: Optional[str] = None,
        error_code: Optional[str] = None,
        error_category: Optional[str] = None
    ):
        """Update task stage attribution."""
        async with aiosqlite.connect(self.db_path) as db:
            updates = []
            params = []
            if current_stage is not None:
                updates.append("current_stage = ?")
                params.append(current_stage)
            if failure_stage is not None:
                updates.append("failure_stage = ?")
                params.append(failure_stage)
            if error_code is not None:
                updates.append("error_code = ?")
                params.append(error_code)
            if error_category is not None:
                updates.append("error_category = ?")
                params.append(error_category)

            if updates:
                updates.append("last_event_at = CURRENT_TIMESTAMP")
                params.append(task_id)
                query = f"UPDATE tasks SET {', '.join(updates)} WHERE task_id = ?"
                await db.execute(query, params)
                await db.commit()
    
    async def get_task(self, task_id: str) -> Optional[Task]:
        """Get task by ID"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,))
            row = await cursor.fetchone()
            if row:
                return self._decode_task_row(dict(row))
            return None
    
    # Request log operations
    async def log_request(self, log: RequestLog) -> int:
        """Log a request and return log ID"""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("""
                INSERT INTO request_logs (
                    token_id, task_id, operation, request_body, response_body,
                    stage, trigger_source, is_redacted, status_code, duration
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                log.token_id,
                log.task_id,
                log.operation,
                log.request_body,
                log.response_body,
                log.stage,
                log.trigger_source,
                log.is_redacted,
                log.status_code,
                log.duration,
            ))
            await db.commit()
            return cursor.lastrowid

    async def update_request_log(self, log_id: int, response_body: Optional[str] = None,
                                 status_code: Optional[int] = None, duration: Optional[float] = None):
        """Update request log with completion data"""
        async with aiosqlite.connect(self.db_path) as db:
            updates = []
            params = []

            if response_body is not None:
                updates.append("response_body = ?")
                params.append(response_body)
            if status_code is not None:
                updates.append("status_code = ?")
                params.append(status_code)
            if duration is not None:
                updates.append("duration = ?")
                params.append(duration)

            if updates:
                updates.append("updated_at = CURRENT_TIMESTAMP")
                params.append(log_id)
                query = f"UPDATE request_logs SET {', '.join(updates)} WHERE id = ?"
                await db.execute(query, params)
                await db.commit()

    async def update_request_log_task_id(self, log_id: int, task_id: str):
        """Update request log with task_id"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                UPDATE request_logs
                SET task_id = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (task_id, log_id))
            await db.commit()

    async def get_recent_logs(self, limit: int = 100) -> List[dict]:
        """Get recent logs with token email, collapsed to one primary row per task."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("""
                WITH primary_task_logs AS (
                    SELECT task_id, MIN(id) AS primary_log_id
                    FROM request_logs
                    WHERE task_id IS NOT NULL
                    GROUP BY task_id
                )
                SELECT
                    rl.id,
                    rl.token_id,
                    rl.task_id,
                    rl.operation,
                    rl.request_body,
                    rl.response_body,
                    rl.stage,
                    rl.trigger_source,
                    rl.is_redacted,
                    rl.status_code,
                    rl.duration,
                    rl.created_at,
                    rl.updated_at,
                    COALESCE(rl.updated_at, rl.created_at) AS event_at,
                    t.email as token_email,
                    t.username as token_username
                FROM request_logs rl
                LEFT JOIN tokens t ON rl.token_id = t.id
                LEFT JOIN primary_task_logs ptl ON rl.task_id = ptl.task_id
                WHERE rl.task_id IS NULL OR rl.id = ptl.primary_log_id
                ORDER BY datetime(COALESCE(rl.updated_at, rl.created_at)) DESC, rl.id DESC
                LIMIT ?
            """, (limit,))
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def clear_all_logs(self):
        """Clear all request logs"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM request_logs")
            await db.commit()

    async def update_token_browser_state(
        self,
        token_id: int,
        browser_provider: Optional[str] = None,
        browser_profile_id: Optional[str] = None,
        sora_available: Optional[bool] = None,
        account_status: Optional[str] = None,
        last_auth_refresh_at: Optional[datetime] = None,
        last_auth_result: Optional[str] = None,
        last_auth_error_reason: Optional[str] = None,
        last_challenge_reason: Optional[str] = None,
        last_browser_user_agent: Optional[str] = None,
        last_device_id: Optional[str] = None,
        last_auth_context_hash: Optional[str] = None,
        last_auth_context_expires_at: Optional[datetime] = None,
        last_auth_page_url: Optional[str] = None,
    ):
        """Persist browser binding and auth snapshot metadata for a token."""
        await self.update_token(
            token_id=token_id,
            browser_provider=browser_provider,
            browser_profile_id=browser_profile_id,
            sora_available=sora_available,
            account_status=account_status,
            last_auth_refresh_at=last_auth_refresh_at,
            last_auth_result=last_auth_result,
            last_auth_error_reason=last_auth_error_reason,
            last_challenge_reason=last_challenge_reason,
            last_browser_user_agent=last_browser_user_agent,
            last_device_id=last_device_id,
            last_auth_context_hash=last_auth_context_hash,
            last_auth_context_expires_at=last_auth_context_expires_at,
            last_auth_page_url=last_auth_page_url,
        )

    async def create_mutation_attempt(
        self,
        token_id: Optional[int],
        task_id: Optional[str],
        mutation_type: str,
        strategy: str,
        stage: str,
        status: str,
        provider: Optional[str] = None,
        profile_id: Optional[str] = None,
        window_id: Optional[str] = None,
        page_url: Optional[str] = None,
        egress_binding: Optional[str] = None,
        details: Optional[str] = None,
        error_code: Optional[str] = None,
        error_reason: Optional[str] = None,
    ) -> int:
        """Create a structured mutation attempt record."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("""
                INSERT INTO mutation_attempts (
                    token_id, task_id, mutation_type, strategy, stage, status,
                    provider, profile_id, window_id, page_url, egress_binding,
                    details, error_code, error_reason
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                token_id,
                task_id,
                mutation_type,
                strategy,
                stage,
                status,
                provider,
                profile_id,
                window_id,
                page_url,
                egress_binding,
                details,
                error_code,
                error_reason,
            ))
            await db.commit()
            return cursor.lastrowid

    async def update_mutation_attempt(
        self,
        attempt_id: int,
        task_id: Optional[str] = None,
        stage: Optional[str] = None,
        status: Optional[str] = None,
        window_id: Optional[str] = None,
        page_url: Optional[str] = None,
        egress_binding: Optional[str] = None,
        details: Optional[str] = None,
        error_code: Optional[str] = None,
        error_reason: Optional[str] = None,
    ):
        """Update a mutation attempt record."""
        async with aiosqlite.connect(self.db_path) as db:
            updates = []
            params = []
            if task_id is not None:
                updates.append("task_id = ?")
                params.append(task_id)
            if stage is not None:
                updates.append("stage = ?")
                params.append(stage)
            if status is not None:
                updates.append("status = ?")
                params.append(status)
            if window_id is not None:
                updates.append("window_id = ?")
                params.append(window_id)
            if page_url is not None:
                updates.append("page_url = ?")
                params.append(page_url)
            if egress_binding is not None:
                updates.append("egress_binding = ?")
                params.append(egress_binding)
            if details is not None:
                updates.append("details = ?")
                params.append(details)
            if error_code is not None:
                updates.append("error_code = ?")
                params.append(error_code)
            if error_reason is not None:
                updates.append("error_reason = ?")
                params.append(error_reason)
            if updates:
                updates.append("updated_at = CURRENT_TIMESTAMP")
                params.append(attempt_id)
                query = f"UPDATE mutation_attempts SET {', '.join(updates)} WHERE id = ?"
                await db.execute(query, params)
                await db.commit()

    async def create_task_event(
        self,
        task_id: Optional[str],
        token_id: Optional[int],
        event_type: str,
        stage: Optional[str],
        status: str,
        message: Optional[str] = None,
        details: Optional[str] = None,
        error_code: Optional[str] = None,
        error_reason: Optional[str] = None,
    ) -> int:
        """Create a structured task event."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("""
                INSERT INTO task_events (
                    task_id, token_id, event_type, stage, status,
                    message, details, error_code, error_reason
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                task_id,
                token_id,
                event_type,
                stage,
                status,
                message,
                details,
                error_code,
                error_reason,
            ))
            await db.commit()
            return cursor.lastrowid

    async def create_error_attribution(
        self,
        task_id: Optional[str],
        token_id: Optional[int],
        mutation_type: Optional[str],
        stage: str,
        error_code: Optional[str],
        error_reason: Optional[str],
        details: Optional[str] = None,
    ) -> int:
        """Create an error attribution record."""
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute("""
                INSERT INTO error_attributions (
                    task_id, token_id, mutation_type, stage,
                    error_code, error_reason, details
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                task_id,
                token_id,
                mutation_type,
                stage,
                error_code,
                error_reason,
                details,
            ))
            await db.commit()
            return cursor.lastrowid

    # Admin config operations
    async def get_admin_config(self) -> AdminConfig:
        """Get admin configuration"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM admin_config WHERE id = 1")
            row = await cursor.fetchone()
            if row:
                return AdminConfig(**dict(row))
            # If no row exists, return a default config with placeholder values
            # This should not happen in normal operation as _ensure_config_rows should create it
            return AdminConfig(admin_username="admin", admin_password="admin", api_key="han1234")
    
    async def update_admin_config(self, config: AdminConfig):
        """Update admin configuration"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                UPDATE admin_config
                SET admin_username = ?, admin_password = ?, api_key = ?, error_ban_threshold = ?,
                    task_retry_enabled = ?, task_max_retries = ?, auto_disable_on_401 = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = 1
            """, (config.admin_username, config.admin_password, config.api_key, config.error_ban_threshold,
                  config.task_retry_enabled, config.task_max_retries, config.auto_disable_on_401))
            await db.commit()
    
    # Proxy config operations
    async def get_proxy_config(self) -> ProxyConfig:
        """Get proxy configuration"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM proxy_config WHERE id = 1")
            row = await cursor.fetchone()
            if row:
                return ProxyConfig(**dict(row))
            # If no row exists, return a default config
            # This should not happen in normal operation as _ensure_config_rows should create it
            return ProxyConfig(proxy_enabled=False)
    
    async def update_proxy_config(
        self,
        enabled: bool,
        proxy_url: Optional[str],
        image_upload_proxy_enabled: bool = False,
        image_upload_proxy_url: Optional[str] = None
    ):
        """Update proxy configuration"""
        proxy_url = proxy_url if proxy_url else None
        image_upload_proxy_url = image_upload_proxy_url if image_upload_proxy_url else None
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                UPDATE proxy_config
                SET proxy_enabled = ?,
                    proxy_url = ?,
                    image_upload_proxy_enabled = ?,
                    image_upload_proxy_url = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = 1
            """, (enabled, proxy_url, image_upload_proxy_enabled, image_upload_proxy_url))
            await db.commit()

    # Watermark-free config operations
    async def get_watermark_free_config(self) -> WatermarkFreeConfig:
        """Get watermark-free configuration"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM watermark_free_config WHERE id = 1")
            row = await cursor.fetchone()
            if row:
                return WatermarkFreeConfig(**dict(row))
            # If no row exists, return a default config
            # This should not happen in normal operation as _ensure_config_rows should create it
            return WatermarkFreeConfig(watermark_free_enabled=False, parse_method="third_party")

    async def update_watermark_free_config(self, enabled: bool, parse_method: str = None,
                                          custom_parse_url: str = None, custom_parse_token: str = None,
                                          fallback_on_failure: bool = None):
        """Update watermark-free configuration"""
        async with aiosqlite.connect(self.db_path) as db:
            if parse_method is None and custom_parse_url is None and custom_parse_token is None and fallback_on_failure is None:
                # Only update enabled status
                await db.execute("""
                    UPDATE watermark_free_config
                    SET watermark_free_enabled = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = 1
                """, (enabled,))
            else:
                # Update all fields
                await db.execute("""
                    UPDATE watermark_free_config
                    SET watermark_free_enabled = ?, parse_method = ?, custom_parse_url = ?,
                        custom_parse_token = ?, fallback_on_failure = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE id = 1
                """, (enabled, parse_method or "third_party", custom_parse_url, custom_parse_token,
                      fallback_on_failure if fallback_on_failure is not None else True))
            await db.commit()

    # Cache config operations
    async def get_cache_config(self) -> CacheConfig:
        """Get cache configuration"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM cache_config WHERE id = 1")
            row = await cursor.fetchone()
            if row:
                return CacheConfig(**dict(row))
            # If no row exists, return a default config
            # This should not happen in normal operation as _ensure_config_rows should create it
            return CacheConfig(cache_enabled=False, cache_timeout=600)

    async def update_cache_config(self, enabled: bool = None, timeout: int = None, base_url: Optional[str] = None):
        """Update cache configuration"""
        async with aiosqlite.connect(self.db_path) as db:
            # Get current config first
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM cache_config WHERE id = 1")
            row = await cursor.fetchone()

            if row:
                current = dict(row)
                # Update only provided fields
                new_enabled = enabled if enabled is not None else current.get("cache_enabled", False)
                new_timeout = timeout if timeout is not None else current.get("cache_timeout", 600)
                new_base_url = base_url if base_url is not None else current.get("cache_base_url")
            else:
                new_enabled = enabled if enabled is not None else False
                new_timeout = timeout if timeout is not None else 600
                new_base_url = base_url

            # Convert empty string to None
            new_base_url = new_base_url if new_base_url else None

            await db.execute("""
                UPDATE cache_config
                SET cache_enabled = ?, cache_timeout = ?, cache_base_url = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = 1
            """, (new_enabled, new_timeout, new_base_url))
            await db.commit()

    # Generation config operations
    async def get_generation_config(self) -> GenerationConfig:
        """Get generation configuration"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM generation_config WHERE id = 1")
            row = await cursor.fetchone()
            if row:
                return GenerationConfig(**dict(row))
            # If no row exists, return a default config
            # This should not happen in normal operation as _ensure_config_rows should create it
            return GenerationConfig(image_timeout=300, video_timeout=3000)

    async def update_generation_config(self, image_timeout: int = None, video_timeout: int = None):
        """Update generation configuration"""
        async with aiosqlite.connect(self.db_path) as db:
            # Get current config first
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM generation_config WHERE id = 1")
            row = await cursor.fetchone()

            if row:
                current = dict(row)
                # Update only provided fields
                new_image_timeout = image_timeout if image_timeout is not None else current.get("image_timeout", 300)
                new_video_timeout = video_timeout if video_timeout is not None else current.get("video_timeout", 3000)
            else:
                new_image_timeout = image_timeout if image_timeout is not None else 300
                new_video_timeout = video_timeout if video_timeout is not None else 3000

            await db.execute("""
                UPDATE generation_config
                SET image_timeout = ?, video_timeout = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = 1
            """, (new_image_timeout, new_video_timeout))
            await db.commit()

    # Token refresh config operations
    async def get_token_refresh_config(self) -> TokenRefreshConfig:
        """Get token refresh configuration"""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM token_refresh_config WHERE id = 1")
            row = await cursor.fetchone()
            if row:
                return TokenRefreshConfig(**dict(row))
            # If no row exists, return a default config
            # This should not happen in normal operation as _ensure_config_rows should create it
            return TokenRefreshConfig(at_auto_refresh_enabled=False)

    async def update_token_refresh_config(self, at_auto_refresh_enabled: bool):
        """Update token refresh configuration"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                UPDATE token_refresh_config
                SET at_auto_refresh_enabled = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = 1
            """, (at_auto_refresh_enabled,))
            await db.commit()

    # Call logic config operations
    async def get_call_logic_config(self) -> "CallLogicConfig":
        """Get call logic configuration"""
        from .models import CallLogicConfig
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM call_logic_config WHERE id = 1")
            row = await cursor.fetchone()
            if row:
                row_dict = dict(row)
                if not row_dict.get("call_mode"):
                    row_dict["call_mode"] = "polling" if row_dict.get("polling_mode_enabled") else "default"
                poll_interval = row_dict.get("poll_interval", 2.5)
                try:
                    poll_interval = float(poll_interval)
                except (TypeError, ValueError):
                    poll_interval = 2.5
                if poll_interval <= 0:
                    poll_interval = 2.5
                row_dict["poll_interval"] = poll_interval
                return CallLogicConfig(**row_dict)
            return CallLogicConfig(call_mode="default", polling_mode_enabled=False, poll_interval=2.5)

    async def update_call_logic_config(self, call_mode: str, poll_interval: Optional[float] = None):
        """Update call logic configuration"""
        normalized = "polling" if call_mode == "polling" else "default"
        polling_mode_enabled = normalized == "polling"
        async with aiosqlite.connect(self.db_path) as db:
            effective_poll_interval = 2.5
            cursor = await db.execute("SELECT poll_interval FROM call_logic_config WHERE id = 1")
            row = await cursor.fetchone()
            if row and row[0] is not None:
                try:
                    effective_poll_interval = float(row[0])
                except (TypeError, ValueError):
                    effective_poll_interval = 2.5
            if effective_poll_interval <= 0:
                effective_poll_interval = 2.5

            if poll_interval is not None:
                try:
                    effective_poll_interval = float(poll_interval)
                except (TypeError, ValueError):
                    effective_poll_interval = 2.5
                if effective_poll_interval <= 0:
                    effective_poll_interval = 2.5

            # Use INSERT OR REPLACE to ensure the row exists
            await db.execute("""
                INSERT OR REPLACE INTO call_logic_config (id, call_mode, polling_mode_enabled, poll_interval, updated_at)
                VALUES (1, ?, ?, ?, CURRENT_TIMESTAMP)
            """, (normalized, polling_mode_enabled, effective_poll_interval))
            await db.commit()

    # POW proxy config operations
    async def get_pow_proxy_config(self) -> "PowProxyConfig":
        """Get POW proxy configuration"""
        from .models import PowProxyConfig
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM pow_proxy_config WHERE id = 1")
            row = await cursor.fetchone()
            if row:
                return PowProxyConfig(**dict(row))
            return PowProxyConfig(pow_proxy_enabled=False, pow_proxy_url=None)

    async def get_pow_service_config(self) -> "PowServiceConfig":
        """Get POW service configuration"""
        from .models import PowServiceConfig
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM pow_service_config WHERE id = 1")
            row = await cursor.fetchone()
            if row:
                return PowServiceConfig(**dict(row))
            return PowServiceConfig(
                mode="local",
                use_token_for_pow=False,
                server_url=None,
                api_key=None,
                proxy_enabled=False,
                proxy_url=None
            )

    async def update_pow_proxy_config(self, pow_proxy_enabled: bool, pow_proxy_url: Optional[str] = None):
        """Update POW proxy configuration"""
        async with aiosqlite.connect(self.db_path) as db:
            # Use INSERT OR REPLACE to ensure the row exists
            await db.execute("""
                INSERT OR REPLACE INTO pow_proxy_config (id, pow_proxy_enabled, pow_proxy_url, updated_at)
                VALUES (1, ?, ?, CURRENT_TIMESTAMP)
            """, (pow_proxy_enabled, pow_proxy_url))
            await db.commit()

    async def update_pow_service_config(
        self,
        mode: str,
        use_token_for_pow: bool = False,
        server_url: Optional[str] = None,
        api_key: Optional[str] = None,
        proxy_enabled: Optional[bool] = None,
        proxy_url: Optional[str] = None
    ):
        """Update POW service configuration"""
        async with aiosqlite.connect(self.db_path) as db:
            # Use INSERT OR REPLACE to ensure the row exists
            await db.execute("""
                INSERT OR REPLACE INTO pow_service_config (id, mode, use_token_for_pow, server_url, api_key, proxy_enabled, proxy_url, updated_at)
                VALUES (1, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """, (mode, use_token_for_pow, server_url, api_key, proxy_enabled, proxy_url))
            await db.commit()


