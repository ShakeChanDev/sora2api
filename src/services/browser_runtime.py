"""Browser runtime locks and startup queue."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Dict


class BrowserRuntime:
    """Coordinates browser startup, profile, and window access."""

    def __init__(self):
        self._startup_lock = asyncio.Lock()
        self._registry_lock = asyncio.Lock()
        self._profile_locks: Dict[str, asyncio.Lock] = {}
        self._window_locks: Dict[str, asyncio.Lock] = {}

    async def _get_lock(self, registry: Dict[str, asyncio.Lock], key: str) -> asyncio.Lock:
        async with self._registry_lock:
            lock = registry.get(key)
            if lock is None:
                lock = asyncio.Lock()
                registry[key] = lock
            return lock

    @asynccontextmanager
    async def startup_queue(self):
        """Serialize browser startup and profile attach."""
        await self._startup_lock.acquire()
        try:
            yield
        finally:
            self._startup_lock.release()

    @asynccontextmanager
    async def profile_lock(self, profile_id: str):
        """Serialize mutations on the same profile."""
        lock = await self._get_lock(self._profile_locks, profile_id)
        await lock.acquire()
        try:
            yield
        finally:
            lock.release()

    @asynccontextmanager
    async def window_lock(self, window_id: str):
        """Serialize access to the same browser window/page."""
        lock = await self._get_lock(self._window_locks, window_id)
        await lock.acquire()
        try:
            yield
        finally:
            lock.release()
