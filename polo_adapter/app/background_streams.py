"""Background stream task management."""
from __future__ import annotations

import asyncio
import logging


class BackgroundStreamDrainer:
    """Track and drain long-lived upstream stream tasks."""

    def __init__(self):
        self._tasks: set[asyncio.Task] = set()
        self.logger = logging.getLogger("polo_adapter.background")

    def start(self, name: str, coro) -> asyncio.Task:
        task = asyncio.create_task(coro, name=name)
        self._tasks.add(task)
        task.add_done_callback(self._cleanup_task)
        return task

    def _cleanup_task(self, task: asyncio.Task) -> None:
        self._tasks.discard(task)
        if task.cancelled():
            self.logger.info("Background task %s cancelled", task.get_name())
            return
        exc = task.exception()
        if exc is not None:
            self.logger.warning("Background task %s failed: %s", task.get_name(), exc)

    @property
    def active_count(self) -> int:
        return len(self._tasks)

    async def close(self) -> None:
        if not self._tasks:
            return
        tasks = list(self._tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()
