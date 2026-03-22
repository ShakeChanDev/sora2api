"""Browser runtime locks and startup queue."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Awaitable, Callable, Dict

from ..core.logger import debug_logger


class BrowserRuntime:
    """Coordinates browser startup, profile, and window access."""

    def __init__(self):
        self._startup_lock = asyncio.Lock()
        self._registry_lock = asyncio.Lock()
        self._profile_locks: Dict[str, asyncio.Lock] = {}
        self._window_locks: Dict[str, asyncio.Lock] = {}
        self._scheduled_profile_stops: Dict[str, asyncio.Task] = {}

    async def _get_lock(self, registry: Dict[str, asyncio.Lock], key: str) -> asyncio.Lock:
        async with self._registry_lock:
            lock = registry.get(key)
            if lock is None:
                lock = asyncio.Lock()
                registry[key] = lock
            return lock

    async def _pop_scheduled_profile_stop(self, profile_id: str) -> asyncio.Task | None:
        async with self._registry_lock:
            return self._scheduled_profile_stops.pop(profile_id, None)

    async def cancel_scheduled_profile_stop(self, profile_id: str):
        """Cancel a pending delayed stop for the given profile, if any."""
        task = await self._pop_scheduled_profile_stop(profile_id)
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception as exc:  # pragma: no cover - defensive logging only
            debug_logger.log_warning(f"[BrowserRuntime] Failed while cancelling delayed stop for {profile_id}: {exc}")

    @asynccontextmanager
    async def startup_queue(self):
        """Serialize browser startup and profile attach."""
        await self._startup_lock.acquire()
        try:
            yield
        finally:
            self._startup_lock.release()

    @asynccontextmanager
    async def profile_lock(self, profile_id: str, cancel_pending_stop: bool = True):
        """Serialize mutations on the same profile."""
        if cancel_pending_stop:
            await self.cancel_scheduled_profile_stop(profile_id)
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

    async def stop_profile_now(self, profile_id: str, stop_action: Callable[[], Awaitable[object]]) -> bool:
        """Cancel delayed stop and stop a profile immediately."""
        await self.cancel_scheduled_profile_stop(profile_id)
        return await self._run_stop_action(profile_id, stop_action)

    async def _run_stop_action(self, profile_id: str, stop_action: Callable[[], Awaitable[object]]) -> bool:
        """Execute the provider stop action and convert failures into warnings."""
        try:
            await stop_action()
            return True
        except Exception as exc:  # pragma: no cover - defensive logging only
            debug_logger.log_warning(f"[BrowserRuntime] Failed to stop profile {profile_id}: {exc}")
            return False

    async def schedule_profile_stop(self, profile_id: str, delay_seconds: int, stop_action: Callable[[], Awaitable[object]]):
        """Schedule a delayed stop for the given profile."""
        await self.cancel_scheduled_profile_stop(profile_id)

        async def _runner():
            try:
                await asyncio.sleep(max(0, delay_seconds))
                async with self.profile_lock(profile_id, cancel_pending_stop=False):
                    await self._run_stop_action(profile_id, stop_action)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # pragma: no cover - defensive logging only
                debug_logger.log_warning(f"[BrowserRuntime] Delayed stop failed for profile {profile_id}: {exc}")
            finally:
                async with self._registry_lock:
                    current = self._scheduled_profile_stops.get(profile_id)
                    if current is task:
                        self._scheduled_profile_stops.pop(profile_id, None)

        task = asyncio.create_task(_runner())
        async with self._registry_lock:
            self._scheduled_profile_stops[profile_id] = task
        return task

    async def shutdown(self):
        """Cancel all delayed stop tasks during application shutdown."""
        async with self._registry_lock:
            tasks = list(self._scheduled_profile_stops.values())
            self._scheduled_profile_stops.clear()
        for task in tasks:
            task.cancel()
        for task in tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception as exc:  # pragma: no cover - defensive logging only
                debug_logger.log_warning(f"[BrowserRuntime] Shutdown cleanup failed: {exc}")
