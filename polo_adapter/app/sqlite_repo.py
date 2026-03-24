"""Readonly SQLite access layer for main-service tables."""
from __future__ import annotations

from pathlib import Path
from typing import Optional, Sequence

import aiosqlite

from .schemas import RequestLogRecord, TaskRecord


class SQLiteReadRepository:
    """Readonly access to the shared SQLite database."""

    def __init__(self, db_path: str):
        self.db_path = Path(db_path).expanduser().resolve()
        self._db_uri = self._build_readonly_uri(self.db_path)

    @staticmethod
    def _build_readonly_uri(db_path: Path) -> str:
        return f"file:{db_path.as_posix()}?mode=ro"

    async def validate_shared_api_key(self, expected_api_key: str) -> None:
        """Ensure adapter and main service use the same fixed API key."""

        async with aiosqlite.connect(self._db_uri, uri=True) as db:
            cursor = await db.execute("SELECT api_key FROM admin_config WHERE id = 1")
            row = await cursor.fetchone()
            if row is None:
                raise RuntimeError("admin_config row is missing from the shared database")
            actual = row[0]
            if actual != expected_api_key:
                raise RuntimeError("POLO_SHARED_API_KEY does not match admin_config.api_key")

    async def get_reference_ids(self, reference_ids: Sequence[str]) -> set[str]:
        """Return the subset of reference ids that exist in the shared database."""

        if not reference_ids:
            return set()

        placeholders = ", ".join(["?"] * len(reference_ids))
        query = f'SELECT reference_id FROM "references" WHERE reference_id IN ({placeholders})'
        async with aiosqlite.connect(self._db_uri, uri=True) as db:
            cursor = await db.execute(query, tuple(reference_ids))
            rows = await cursor.fetchall()
            return {row[0] for row in rows}

    async def get_task(self, task_id: str) -> Optional[TaskRecord]:
        """Get an exact task match by task_id."""

        async with aiosqlite.connect(self._db_uri, uri=True) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT task_id, status, progress, result_urls, error_message, created_at, completed_at
                FROM tasks
                WHERE task_id = ?
                """,
                (task_id,),
            )
            row = await cursor.fetchone()
            if row is None:
                return None
            return TaskRecord(
                task_id=row["task_id"],
                status=row["status"],
                progress=float(row["progress"] or 0.0),
                result_urls=row["result_urls"],
                error_message=row["error_message"],
                created_at=row["created_at"],
                completed_at=row["completed_at"],
            )

    async def get_latest_request_log(self, task_id: str) -> Optional[RequestLogRecord]:
        """Get the latest request log associated with the task."""

        async with aiosqlite.connect(self._db_uri, uri=True) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT task_id, response_body, status_code, created_at, updated_at
                FROM request_logs
                WHERE task_id = ?
                ORDER BY datetime(COALESCE(updated_at, created_at)) DESC, id DESC
                LIMIT 1
                """,
                (task_id,),
            )
            row = await cursor.fetchone()
            if row is None:
                return None
            return RequestLogRecord(
                task_id=row["task_id"],
                response_body=row["response_body"],
                status_code=row["status_code"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
