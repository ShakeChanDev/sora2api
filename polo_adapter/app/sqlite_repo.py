"""Read-only SQLite access for the adapter."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import aiosqlite

from .errors import AdapterError


@dataclass
class TaskRecord:
    task_id: str
    status: str
    progress: float
    result_urls: str | None
    error_message: str | None
    created_at: Any
    completed_at: Any


class SQLiteReadRepository:
    """Read-only repository against the shared main-service SQLite DB."""

    def __init__(self, db_path: str, busy_timeout_ms: int = 5000):
        self.db_path = db_path
        self.busy_timeout_ms = busy_timeout_ms
        self.db_uri = self._build_read_only_uri(db_path)

    @staticmethod
    def _build_read_only_uri(db_path: str) -> str:
        if db_path.startswith("file:"):
            separator = "&" if "?" in db_path else "?"
            return f"{db_path}{separator}mode=ro"
        return f"{Path(db_path).resolve().as_uri()}?mode=ro"

    async def _connect(self) -> aiosqlite.Connection:
        try:
            db = await aiosqlite.connect(self.db_uri, uri=True)
            db.row_factory = aiosqlite.Row
            await db.execute(f"PRAGMA busy_timeout = {int(self.busy_timeout_ms)}")
            return db
        except Exception as exc:
            raise AdapterError(
                status_code=500,
                message=f"Unable to open SQLite database: {exc}",
                error_type="server_error",
                code="sqlite_unavailable",
            ) from exc

    async def close(self) -> None:
        return None

    async def get_existing_reference_ids(self, reference_ids: list[str]) -> set[str]:
        if not reference_ids:
            return set()
        placeholders = ", ".join("?" for _ in reference_ids)
        query = f'SELECT reference_id FROM "references" WHERE reference_id IN ({placeholders})'
        db = await self._connect()
        try:
            cursor = await db.execute(query, tuple(reference_ids))
            rows = await cursor.fetchall()
        finally:
            await db.close()
        return {str(row["reference_id"]) for row in rows}

    async def get_task(self, task_id: str) -> TaskRecord | None:
        db = await self._connect()
        try:
            cursor = await db.execute(
                """
                SELECT task_id, status, progress, result_urls, error_message, created_at, completed_at
                FROM tasks
                WHERE task_id = ?
                """,
                (task_id,),
            )
            row = await cursor.fetchone()
        finally:
            await db.close()
        if row is None:
            return None
        return TaskRecord(
            task_id=str(row["task_id"]),
            status=str(row["status"] or ""),
            progress=float(row["progress"] or 0),
            result_urls=row["result_urls"],
            error_message=row["error_message"],
            created_at=row["created_at"],
            completed_at=row["completed_at"],
        )

    async def get_latest_request_log_response(self, task_id: str) -> str | None:
        db = await self._connect()
        try:
            cursor = await db.execute(
                """
                SELECT response_body
                FROM request_logs
                WHERE task_id = ?
                ORDER BY datetime(COALESCE(updated_at, created_at)) DESC, id DESC
                LIMIT 1
                """,
                (task_id,),
            )
            row = await cursor.fetchone()
        finally:
            await db.close()
        if row is None:
            return None
        return row["response_body"]
