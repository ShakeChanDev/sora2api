"""Regression tests for strict video polling context requirements."""
import asyncio
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from src.services.generation_handler import GenerationError, GenerationHandler
from src.services.polling_client import PollingClientError


class _FakeDb:
    def __init__(self):
        self.task_stage_updates = []
        self.task_updates = []
        self.task_events = []
        self.error_attributions = []

    async def get_watermark_free_config(self):
        return SimpleNamespace(watermark_free_enabled=False)

    async def create_task_event(self, **kwargs):
        self.task_events.append(kwargs)
        return len(self.task_events)

    async def update_task_stage(self, task_id, **kwargs):
        self.task_stage_updates.append((task_id, kwargs))

    async def update_task(self, task_id, status, progress, result_urls=None, error_message=None, current_stage=None):
        self.task_updates.append((task_id, status, progress, error_message, current_stage))

    async def create_error_attribution(self, **kwargs):
        self.error_attributions.append(kwargs)
        return len(self.error_attributions)


class _FakePollingClient:
    mutation_executor = None

    async def load_task_polling_context(self, task_id):
        return None


class _FakeTokenManager:
    def __init__(self, active_tokens=None):
        self._active_tokens = active_tokens or []

    async def get_active_tokens(self):
        return list(self._active_tokens)


class GenerationHandlerVideoPollingTests(unittest.TestCase):
    def test_missing_polling_context_fails_immediately(self):
        async def scenario():
            db = _FakeDb()
            load_balancer = SimpleNamespace(token_lock=None, proxy_manager=None)
            handler = GenerationHandler(
                sora_client=SimpleNamespace(),
                token_manager=SimpleNamespace(),
                load_balancer=load_balancer,
                db=db,
                proxy_manager=None,
                concurrency_manager=None,
                polling_client=_FakePollingClient(),
            )

            async def _fast_sleep(_):
                return None

            with patch("src.services.generation_handler.asyncio.sleep", _fast_sleep):
                generator = handler._poll_task_result(
                    task_id="task_1",
                    token="at",
                    is_video=True,
                    stream=False,
                    prompt="test",
                    token_id=1,
                    log_id=None,
                    start_time=time.time(),
                    polling_context=None,
                )
                with self.assertRaises(PollingClientError) as ctx:
                    await generator.__anext__()

            self.assertEqual(ctx.exception.code, "polling_context_missing")
            self.assertTrue(any(event["event_type"] == "polling_failed" for event in db.task_events))
            self.assertTrue(any(update[1].get("error_code") == "polling_context_missing" for update in db.task_stage_updates))
            self.assertTrue(any(update[1] == "failed" for update in db.task_updates))
            self.assertTrue(any(item["error_code"] == "polling_context_missing" for item in db.error_attributions))

        asyncio.run(scenario())

    def test_missing_video_proxy_binding_raises_explicit_error(self):
        async def scenario():
            db = _FakeDb()
            token_obj = SimpleNamespace(
                id=1,
                plan_type="chatgpt_free",
                video_enabled=True,
                sora2_supported=True,
                sora2_cooldown_until=None,
                browser_provider="nst",
                browser_profile_id="profile-1",
                proxy_url=None,
            )
            load_balancer = SimpleNamespace(
                token_lock=None,
                proxy_manager=None,
                select_token=lambda **kwargs: asyncio.sleep(0, result=None),
            )
            handler = GenerationHandler(
                sora_client=SimpleNamespace(),
                token_manager=_FakeTokenManager([token_obj]),
                load_balancer=load_balancer,
                db=db,
                proxy_manager=None,
                concurrency_manager=None,
                polling_client=_FakePollingClient(),
            )
            with self.assertRaises(GenerationError) as ctx:
                await handler._select_video_token_or_raise("No available video tokens")
            self.assertIn("browser_proxy_binding_required", str(ctx.exception))

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
