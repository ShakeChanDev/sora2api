"""Regression tests for strict video polling context requirements."""
import asyncio
import json
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from src.services.generation_handler import GenerationError, GenerationHandler
from src.services.polling_client import PollingClientError


class _FakeDb:
    def __init__(self, admin_config=None):
        self.task_stage_updates = []
        self.task_updates = []
        self.task_events = []
        self.error_attributions = []
        self.task_polling_context_updates = []
        self.token_status_updates = []
        self.tasks_by_id = {}
        self.log_updates = []
        self.request_log_statuses = {}
        self.request_log_rows = {}
        self.next_log_id = 1
        self.admin_config = admin_config or SimpleNamespace(
            task_retry_enabled=True,
            task_max_retries=0,
            auto_disable_on_401=False,
        )

    async def get_watermark_free_config(self):
        return SimpleNamespace(watermark_free_enabled=False)

    async def create_task_event(self, **kwargs):
        self.task_events.append(kwargs)
        return len(self.task_events)

    async def update_task_stage(self, task_id, **kwargs):
        self.task_stage_updates.append((task_id, kwargs))
        task = self.tasks_by_id.setdefault(task_id, SimpleNamespace(task_id=task_id, result_urls=None))
        for key, value in kwargs.items():
            setattr(task, key, value)

    async def update_task(self, task_id, status, progress, result_urls=None, error_message=None, current_stage=None):
        self.task_updates.append((task_id, status, progress, error_message, current_stage, result_urls))
        task = self.tasks_by_id.setdefault(task_id, SimpleNamespace(task_id=task_id, result_urls=None))
        task.status = status
        task.progress = progress
        task.result_urls = result_urls
        task.error_message = error_message
        if current_stage is not None:
            task.current_stage = current_stage

    async def update_task_polling_context(self, task_id, polling_context, auth_snapshot_id=None):
        self.task_polling_context_updates.append((task_id, polling_context, auth_snapshot_id))
        task = self.tasks_by_id.setdefault(task_id, SimpleNamespace(task_id=task_id, result_urls=None))
        task.polling_context = polling_context
        task.auth_snapshot_id = auth_snapshot_id

    async def create_task(self, task):
        self.tasks_by_id[task.task_id] = task

    async def get_task(self, task_id):
        return self.tasks_by_id.get(task_id)

    async def create_error_attribution(self, **kwargs):
        self.error_attributions.append(kwargs)
        return len(self.error_attributions)

    async def get_admin_config(self):
        return self.admin_config

    async def update_token_status(self, token_id, enabled):
        self.token_status_updates.append((token_id, enabled))

    async def log_request(self, log):
        log_id = self.next_log_id
        self.next_log_id += 1
        self.request_log_rows[log_id] = {
            "task_id": log.task_id,
            "status_code": log.status_code,
            "response_body": log.response_body,
            "duration": log.duration,
        }
        self.request_log_statuses[log_id] = log.status_code
        return log_id

    async def update_request_log(self, log_id, response_body=None, status_code=None, duration=None):
        self.log_updates.append((log_id, response_body, status_code, duration))
        row = self.request_log_rows.setdefault(log_id, {})
        if response_body is not None:
            row["response_body"] = response_body
        if status_code is not None:
            row["status_code"] = status_code
            self.request_log_statuses[log_id] = status_code
        if duration is not None:
            row["duration"] = duration

    async def update_request_log_task_id(self, log_id, task_id):
        row = self.request_log_rows.setdefault(log_id, {})
        row["task_id"] = task_id

    async def get_request_log_status(self, log_id):
        return self.request_log_statuses.get(log_id)


class _FakePollingClient:
    mutation_executor = None

    async def load_task_polling_context(self, task_id):
        return None


class _EventuallyConsistentPollingClient:
    mutation_executor = None

    def __init__(self):
        self.pending_calls = 0
        self.drafts_calls = 0

    async def load_task_polling_context(self, task_id):
        return None

    async def get_pending_tasks(self, task_id, token_id, access_token, polling_context):
        self.pending_calls += 1
        return [], polling_context

    async def get_video_drafts(self, task_id, token_id, access_token, polling_context, limit=15):
        self.drafts_calls += 1
        if self.drafts_calls == 1:
            return {"items": []}, polling_context
        return {
            "items": [
                {
                    "task_id": task_id,
                    "kind": "sora_draft",
                    "url": "https://example.com/video.mp4",
                    "downloadable_url": "https://example.com/video.mp4",
                }
            ]
        }, polling_context


class _PendingReappearsPollingClient:
    mutation_executor = None

    def __init__(self):
        self.pending_calls = 0
        self.drafts_calls = 0

    async def load_task_polling_context(self, task_id):
        return None

    async def get_pending_tasks(self, task_id, token_id, access_token, polling_context):
        self.pending_calls += 1
        if self.pending_calls == 1:
            return [{"id": task_id, "status": "processing", "progress_pct": 0.4}], polling_context
        if self.pending_calls == 3:
            return [{"id": task_id, "status": "processing", "progress_pct": 0.8}], polling_context
        return [], polling_context

    async def get_video_drafts(self, task_id, token_id, access_token, polling_context, limit=15):
        self.drafts_calls += 1
        if self.drafts_calls == 1:
            return {"items": []}, polling_context
        return {
            "items": [
                {
                    "task_id": task_id,
                    "kind": "sora_draft",
                    "url": "https://example.com/rechecked-video.mp4",
                    "downloadable_url": "https://example.com/rechecked-video.mp4",
                }
            ]
        }, polling_context


class _SucceededImageSoraClient:
    async def get_image_tasks(self, token, token_id=None):
        return {
            "task_responses": [
                {
                    "id": "task_1",
                    "status": "succeeded",
                    "progress_pct": 1.0,
                    "generations": [
                        {
                            "url": "https://example.com/image.png",
                        }
                    ],
                }
            ]
        }


class _FakeTokenManager:
    def __init__(self, active_tokens=None):
        self._active_tokens = active_tokens or []
        self.usage = []
        self.success = []
        self.errors = []

    async def get_active_tokens(self):
        return list(self._active_tokens)

    async def record_usage(self, token_id, is_video=False):
        self.usage.append((token_id, is_video))

    async def record_success(self, token_id, is_video=False):
        self.success.append((token_id, is_video))

    async def record_error(self, token_id, is_overload=False):
        self.errors.append((token_id, is_overload))


class _FakeTokenLock:
    async def acquire_lock(self, token_id):
        return True

    async def release_lock(self, token_id):
        return None


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

    def test_drafts_lookup_eventually_succeeds_after_pending_disappears(self):
        async def scenario():
            db = _FakeDb()
            polling_client = _EventuallyConsistentPollingClient()
            load_balancer = SimpleNamespace(token_lock=None, proxy_manager=None)
            handler = GenerationHandler(
                sora_client=SimpleNamespace(),
                token_manager=SimpleNamespace(),
                load_balancer=load_balancer,
                db=db,
                proxy_manager=None,
                concurrency_manager=None,
                polling_client=polling_client,
            )
            polling_context = SimpleNamespace(
                page_url="https://sora.chatgpt.com/explore",
                to_dict=lambda: {"page_url": "https://sora.chatgpt.com/explore"},
            )

            async def _fast_sleep(_):
                return None

            with patch("src.services.generation_handler.asyncio.sleep", _fast_sleep):
                generator = handler._poll_task_result(
                    task_id="task_1",
                    token="at",
                    is_video=True,
                    stream=True,
                    prompt="test",
                    token_id=1,
                    log_id=None,
                    start_time=time.time(),
                    polling_context=polling_context,
                )
                chunks = []
                async for chunk in generator:
                    chunks.append(chunk)

            self.assertGreaterEqual(polling_client.drafts_calls, 2)
            self.assertEqual(polling_client.pending_calls, polling_client.drafts_calls)
            self.assertTrue(any("https://example.com/video.mp4" in chunk for chunk in chunks))
            self.assertTrue(any(update[1] == "completed" for update in db.task_updates))
            self.assertTrue(any(event["event_type"] == "drafts_lookup_miss" for event in db.task_events))
            self.assertFalse(any(update[1].get("current_stage") == "drafts_lookup" for update in db.task_stage_updates))

        asyncio.run(scenario())

    def test_pending_is_rechecked_after_soft_drafts_miss(self):
        async def scenario():
            db = _FakeDb()
            polling_client = _PendingReappearsPollingClient()
            load_balancer = SimpleNamespace(token_lock=None, proxy_manager=None)
            handler = GenerationHandler(
                sora_client=SimpleNamespace(),
                token_manager=SimpleNamespace(),
                load_balancer=load_balancer,
                db=db,
                proxy_manager=None,
                concurrency_manager=None,
                polling_client=polling_client,
            )
            polling_context = SimpleNamespace(
                page_url="https://sora.chatgpt.com/explore",
                to_dict=lambda: {"page_url": "https://sora.chatgpt.com/explore"},
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
                    polling_context=polling_context,
                )
                async for _ in generator:
                    pass

            pending_empty_events = [event for event in db.task_events if event["event_type"] == "pending_empty"]
            drafts_started_events = [event for event in db.task_events if event["event_type"] == "drafts_lookup_started"]

            self.assertEqual(polling_client.pending_calls, 4)
            self.assertEqual(polling_client.drafts_calls, 2)
            self.assertEqual(len(pending_empty_events), 2)
            self.assertEqual(len(drafts_started_events), 2)
            self.assertFalse(any(update[1].get("current_stage") == "drafts_lookup" for update in db.task_stage_updates))
            self.assertTrue(any(update[1] == "completed" for update in db.task_updates))

        asyncio.run(scenario())

    def test_video_success_updates_request_log_before_final_sse_chunks(self):
        async def scenario():
            db = _FakeDb()
            db.request_log_statuses[7] = -1
            db.request_log_rows[7] = {"status_code": -1}
            polling_client = _EventuallyConsistentPollingClient()
            load_balancer = SimpleNamespace(token_lock=None, proxy_manager=None)
            handler = GenerationHandler(
                sora_client=SimpleNamespace(),
                token_manager=SimpleNamespace(),
                load_balancer=load_balancer,
                db=db,
                proxy_manager=None,
                concurrency_manager=None,
                polling_client=polling_client,
            )
            polling_context = SimpleNamespace(
                page_url="https://sora.chatgpt.com/explore",
                to_dict=lambda: {"page_url": "https://sora.chatgpt.com/explore"},
            )
            request_start_time = time.time() - 8

            async def _fast_sleep(_):
                return None

            with patch("src.services.generation_handler.asyncio.sleep", _fast_sleep):
                generator = handler._poll_task_result(
                    task_id="task_1",
                    token="at",
                    is_video=True,
                    stream=True,
                    prompt="test prompt",
                    token_id=1,
                    log_id=7,
                    start_time=request_start_time,
                    polling_context=polling_context,
                    request_log_success_payload={"model": "sora2-landscape-10s"},
                )

                content_chunk = None
                while content_chunk is None:
                    chunk = await generator.__anext__()
                    if "https://example.com/video.mp4" in chunk:
                        content_chunk = chunk

                success_update = [item for item in db.log_updates if item[0] == 7 and item[2] == 200][-1]
                self.assertIn("https://example.com/video.mp4", content_chunk)
                self.assertEqual(await db.get_request_log_status(7), 200)
                self.assertGreater(success_update[3], 7)
                response_body = json.loads(success_update[1])
                self.assertEqual(response_body["model"], "sora2-landscape-10s")
                self.assertEqual(response_body["result_urls"], ["https://example.com/video.mp4"])

                done_chunk = await generator.__anext__()
                self.assertEqual(done_chunk, "data: [DONE]\n\n")

        asyncio.run(scenario())

    def test_image_success_updates_request_log_before_final_sse_chunks(self):
        async def scenario():
            db = _FakeDb()
            db.request_log_statuses[9] = -1
            db.request_log_rows[9] = {"status_code": -1}
            load_balancer = SimpleNamespace(token_lock=_FakeTokenLock(), proxy_manager=None)
            handler = GenerationHandler(
                sora_client=_SucceededImageSoraClient(),
                token_manager=SimpleNamespace(),
                load_balancer=load_balancer,
                db=db,
                proxy_manager=None,
                concurrency_manager=None,
                polling_client=None,
            )
            handler.file_cache = SimpleNamespace(
                download_and_cache=lambda *args, **kwargs: asyncio.sleep(0, result="cached-image.png")
            )
            handler._get_base_url = lambda: "https://local.test"
            request_start_time = time.time() - 6

            async def _fast_sleep(_):
                return None

            with patch("src.services.generation_handler.asyncio.sleep", _fast_sleep):
                generator = handler._poll_task_result(
                    task_id="task_1",
                    token="at",
                    is_video=False,
                    stream=True,
                    prompt="test image prompt",
                    token_id=1,
                    log_id=9,
                    start_time=request_start_time,
                    polling_context=None,
                    request_log_success_payload={"model": "gpt-image"},
                )

                content_chunk = None
                while content_chunk is None:
                    chunk = await generator.__anext__()
                    if "Generated Image" in chunk:
                        content_chunk = chunk

                success_update = [item for item in db.log_updates if item[0] == 9 and item[2] == 200][-1]
                self.assertIn("Generated Image", content_chunk)
                self.assertEqual(await db.get_request_log_status(9), 200)
                self.assertGreater(success_update[3], 5)
                response_body = json.loads(success_update[1])
                self.assertEqual(response_body["model"], "gpt-image")
                self.assertTrue(response_body["result_urls"])

                done_chunk = await generator.__anext__()
                self.assertEqual(done_chunk, "data: [DONE]\n\n")

        asyncio.run(scenario())

    def test_generator_close_after_success_does_not_overwrite_request_log(self):
        async def scenario():
            db = _FakeDb()
            token_manager = _FakeTokenManager()
            token_obj = SimpleNamespace(id=1, token="at", plan_type="chatgpt_free")
            load_balancer = SimpleNamespace(
                token_lock=_FakeTokenLock(),
                proxy_manager=None,
                select_token=lambda **kwargs: asyncio.sleep(0, result=token_obj),
            )
            sora_client = SimpleNamespace(
                generate_image=lambda *args, **kwargs: asyncio.sleep(0, result="task_1"),
            )
            handler = GenerationHandler(
                sora_client=sora_client,
                token_manager=token_manager,
                load_balancer=load_balancer,
                db=db,
                proxy_manager=None,
                concurrency_manager=None,
                polling_client=None,
            )

            async def _poll_success(
                task_id,
                token,
                is_video,
                stream,
                prompt,
                token_id=None,
                log_id=None,
                start_time=None,
                polling_context=None,
                request_log_success_payload=None,
            ):
                await db.update_task(
                    task_id,
                    "completed",
                    100.0,
                    result_urls=json.dumps(["https://example.com/image.png"]),
                    current_stage="completed",
                )
                await handler._mark_request_log_success(
                    log_id,
                    start_time,
                    task_id,
                    prompt,
                    extra_fields=request_log_success_payload,
                )
                yield "data: [DONE]\n\n"

            handler._poll_task_result = _poll_success

            generator = handler.handle_generation(
                model="gpt-image",
                prompt="test close",
                stream=True,
                show_init_message=False,
            )
            first_chunk = await generator.__anext__()
            self.assertEqual(first_chunk, "data: [DONE]\n\n")
            await generator.aclose()

            self.assertEqual(await db.get_request_log_status(1), 200)
            self.assertFalse(any(item[2] == 500 for item in db.log_updates))

        asyncio.run(scenario())

    def test_video_extension_passes_request_log_context_into_polling(self):
        async def scenario():
            db = _FakeDb()
            token_manager = _FakeTokenManager()
            token_obj = SimpleNamespace(id=1, token="at", plan_type="chatgpt_free")
            load_balancer = SimpleNamespace(
                token_lock=None,
                proxy_manager=None,
                select_token=lambda **kwargs: asyncio.sleep(0, result=token_obj),
            )
            sora_client = SimpleNamespace(
                extend_video=lambda **kwargs: asyncio.sleep(0, result="task_1"),
            )
            handler = GenerationHandler(
                sora_client=sora_client,
                token_manager=token_manager,
                load_balancer=load_balancer,
                db=db,
                proxy_manager=None,
                concurrency_manager=None,
                polling_client=None,
            )
            captured = {}

            async def _poll_success(
                task_id,
                token,
                is_video,
                stream,
                prompt,
                token_id=None,
                log_id=None,
                start_time=None,
                polling_context=None,
                request_log_success_payload=None,
            ):
                captured["log_id"] = log_id
                captured["start_time"] = start_time
                captured["payload"] = request_log_success_payload
                await db.update_task(
                    task_id,
                    "completed",
                    100.0,
                    result_urls=json.dumps(["https://example.com/ext.mp4"]),
                    current_stage="completed",
                )
                await handler._mark_request_log_success(
                    log_id,
                    start_time,
                    task_id,
                    prompt,
                    extra_fields=request_log_success_payload,
                )
                yield "data: [DONE]\n\n"

            handler._poll_task_result = _poll_success

            chunks = []
            async for chunk in handler._handle_video_extension(
                "gen_test123 continue the scene",
                {"extension_duration_s": 10},
                "sora2-extension-10s",
            ):
                chunks.append(chunk)

            self.assertEqual(captured["log_id"], 1)
            self.assertIsInstance(captured["start_time"], float)
            self.assertEqual(
                captured["payload"],
                {
                    "model": "sora2-extension-10s",
                    "generation_id": "gen_test123",
                    "extension_duration_s": 10,
                },
            )
            self.assertEqual(await db.get_request_log_status(1), 200)
            self.assertIn("data: [DONE]\n\n", chunks)

        asyncio.run(scenario())

    def test_submit_success_polling_401_does_not_resubmit(self):
        async def scenario():
            db = _FakeDb(
                admin_config=SimpleNamespace(
                    task_retry_enabled=True,
                    task_max_retries=3,
                    auto_disable_on_401=True,
                )
            )
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
            attempts = 0

            async def _fail_after_submit(*args, **kwargs):
                nonlocal attempts
                attempts += 1
                if False:
                    yield None
                raise GenerationError(
                    "polling_drafts_unauthorized: 401 Unauthorized",
                    token_id=9,
                    retry_allowed=False,
                    task_id="task_1",
                    task_submitted=True,
                )

            handler.handle_generation = _fail_after_submit

            chunks = []
            with self.assertRaises(GenerationError):
                async for chunk in handler.handle_generation_with_retry(
                    model="sora2-landscape-10s",
                    prompt="test",
                    stream=True,
                ):
                    chunks.append(chunk)

            reasoning_chunks = [
                json.loads(chunk.removeprefix("data: ").strip())["choices"][0]["delta"]["reasoning_content"]
                for chunk in chunks
            ]
            self.assertEqual(attempts, 1)
            self.assertEqual(db.token_status_updates, [(9, False)])
            self.assertTrue(any("已自动禁用Token 9" in (content or "") for content in reasoning_chunks))
            self.assertFalse(any("正在使用其他Token重试" in (content or "") for content in reasoning_chunks))

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
