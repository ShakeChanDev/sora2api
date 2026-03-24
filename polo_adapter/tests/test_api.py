import json
import sqlite3
import tempfile
import threading
import unittest
from datetime import datetime

import httpx
from fastapi.testclient import TestClient

from polo_adapter.app.config import Settings
from polo_adapter.app.image_downloader import ImageDownloader
from polo_adapter.app.main import create_app
from polo_adapter.app.main_service_client import MainServiceClient


class ChunkStream(httpx.AsyncByteStream):
    def __init__(self, parts, done_event: threading.Event | None = None):
        self.parts = parts
        self.done_event = done_event

    async def __aiter__(self):
        for delay, payload in self.parts:
            if delay:
                await __import__("asyncio").sleep(delay)
            if self.done_event is not None and payload == b"data: [DONE]\n\n":
                self.done_event.set()
            yield payload

    async def aclose(self):
        if self.done_event is not None:
            self.done_event.set()
        return None


class DummyImageDownloader:
    def __init__(self, payload: str = "encoded-image"):
        self.payload = payload
        self.urls = []

    async def download_as_base64(self, image_url: str) -> str:
        self.urls.append(image_url)
        return self.payload

    async def close(self) -> None:
        return None


class NeverCalledMainServiceClient:
    async def create_video_session(self, **_kwargs):
        raise AssertionError("main service client should not be called")

    async def close(self) -> None:
        return None


def make_settings(sqlite_path: str, **overrides) -> Settings:
    payload = {
        "POLO_ADAPTER_API_KEY": "test-key",
        "POLO_ADAPTER_MAIN_BASE_URL": "http://main.test",
        "POLO_ADAPTER_SQLITE_PATH": sqlite_path,
        "POLO_ADAPTER_TASK_ID_WAIT_SECONDS": 0.05,
        "POLO_ADAPTER_IMAGE_TIMEOUT_SECONDS": 1,
        "POLO_ADAPTER_IMAGE_MAX_BYTES": 1024 * 1024,
        "POLO_ADAPTER_IMAGE_MAX_REDIRECTS": 2,
    }
    payload.update(overrides)
    return Settings.model_validate(payload)


def initialize_db(db_path: str) -> None:
    connection = sqlite3.connect(db_path)
    try:
        connection.execute(
            """
            CREATE TABLE tasks (
                task_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                progress FLOAT DEFAULT 0,
                result_urls TEXT,
                error_message TEXT,
                created_at TIMESTAMP,
                completed_at TIMESTAMP
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE request_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT,
                response_body TEXT,
                created_at TIMESTAMP,
                updated_at TIMESTAMP
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE "references" (
                reference_id TEXT PRIMARY KEY,
                name TEXT,
                description TEXT,
                type TEXT,
                asset_path TEXT,
                asset_hash TEXT,
                created_at TIMESTAMP,
                updated_at TIMESTAMP
            )
            """
        )
        connection.commit()
    finally:
        connection.close()


def insert_reference(db_path: str, reference_id: str) -> None:
    connection = sqlite3.connect(db_path)
    try:
        connection.execute(
            """
            INSERT INTO "references" (
                reference_id, name, description, type, asset_path, asset_hash, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                reference_id,
                "ref",
                "ref",
                "other",
                "ref/source.png",
                "hash",
                "2026-03-24 12:00:00",
                "2026-03-24 12:00:00",
            ),
        )
        connection.commit()
    finally:
        connection.close()


def insert_task(
    db_path: str,
    *,
    task_id: str,
    status: str,
    progress: float,
    result_urls: str | None = None,
    error_message: str | None = None,
    created_at: str = "2026-03-24 12:00:00",
    completed_at: str | None = None,
) -> None:
    connection = sqlite3.connect(db_path)
    try:
        connection.execute(
            """
            INSERT INTO tasks (task_id, status, progress, result_urls, error_message, created_at, completed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (task_id, status, progress, result_urls, error_message, created_at, completed_at),
        )
        connection.commit()
    finally:
        connection.close()


def insert_request_log(db_path: str, task_id: str, response_body: str) -> None:
    connection = sqlite3.connect(db_path)
    try:
        connection.execute(
            """
            INSERT INTO request_logs (task_id, response_body, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            (
                task_id,
                response_body,
                "2026-03-24 12:00:01",
                "2026-03-24 12:00:02",
            ),
        )
        connection.commit()
    finally:
        connection.close()


def build_main_service_client(
    *,
    chunks,
    captured_requests: list[dict] | None = None,
    done_event: threading.Event | None = None,
    status_code: int = 200,
    headers: dict[str, str] | None = None,
) -> MainServiceClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if captured_requests is not None:
            captured_requests.append(json.loads(request.content.decode("utf-8")))
        return httpx.Response(
            status_code,
            headers=headers or {"content-type": "text/event-stream"},
            stream=ChunkStream(chunks, done_event=done_event),
        )

    async_client = httpx.AsyncClient(
        base_url="http://main.test",
        transport=httpx.MockTransport(handler),
    )
    return MainServiceClient(
        base_url="http://main.test",
        task_id_wait_seconds=0.05,
        http_client=async_client,
    )


class AdapterApiTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = f"{self.temp_dir.name}/adapter.db"
        initialize_db(self.db_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def make_client(self, *, main_service_client=None, image_downloader=None):
        return TestClient(
            create_app(
                settings=make_settings(self.db_path),
                main_service_client=main_service_client or NeverCalledMainServiceClient(),
                image_downloader=image_downloader or DummyImageDownloader(),
            )
        )

    def auth_headers(self):
        return {"Authorization": "Bearer test-key"}

    def test_create_text_only_returns_pending_and_background_drain_finishes(self):
        captured_requests = []
        done_event = threading.Event()
        main_service_client = build_main_service_client(
            captured_requests=captured_requests,
            done_event=done_event,
            chunks=[
                (0, b'data: {"choices":[{"delta":{"output":[{"task_id":"task_text"}]}}]}\n\n'),
                (0.01, b"data: [DONE]\n\n"),
            ],
        )

        with self.make_client(main_service_client=main_service_client) as client:
            response = client.post(
                "/videos",
                headers=self.auth_headers(),
                json={"prompt": "a panda in snow"},
            )

            self.assertEqual(response.status_code, 200)
            payload = response.json()
            self.assertEqual(payload["id"], "task_text")
            self.assertEqual(payload["status"], "pending")
            self.assertEqual(payload["model"], "sora-2-portrait-15s")
            self.assertTrue(done_event.wait(1))

        self.assertEqual(
            captured_requests[0],
            {
                "model": "sora2-portrait-15s",
                "messages": [{"role": "user", "content": "a panda in snow"}],
                "stream": True,
            },
        )

    def test_create_with_image_url_success(self):
        captured_requests = []
        downloader = DummyImageDownloader(payload="base64-image")
        main_service_client = build_main_service_client(
            captured_requests=captured_requests,
            chunks=[(0, b'data: {"choices":[{"delta":{"output":[{"task_id":"task_image"}]}}]}\n\n')],
        )

        with self.make_client(main_service_client=main_service_client, image_downloader=downloader) as client:
            response = client.post(
                "/videos",
                headers=self.auth_headers(),
                json={"prompt": "with image", "image_url": "https://example.com/image.png"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(downloader.urls, ["https://example.com/image.png"])
        self.assertEqual(captured_requests[0]["image"], "base64-image")

    def test_create_with_references_success(self):
        insert_reference(self.db_path, "s2ref_valid")
        captured_requests = []
        main_service_client = build_main_service_client(
            captured_requests=captured_requests,
            chunks=[(0, b'data: {"choices":[{"delta":{"output":[{"task_id":"task_ref"}]}}]}\n\n')],
        )

        with self.make_client(main_service_client=main_service_client) as client:
            response = client.post(
                "/videos",
                headers=self.auth_headers(),
                json={"prompt": "with refs", "references": ["s2ref_valid", "s2ref_valid"]},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(captured_requests[0]["references"], ["s2ref_valid"])

    def test_create_with_image_and_references_and_style_passthrough(self):
        insert_reference(self.db_path, "s2ref_combo")
        captured_requests = []
        downloader = DummyImageDownloader(payload="combo-base64")
        main_service_client = build_main_service_client(
            captured_requests=captured_requests,
            chunks=[(0, b'data: {"choices":[{"delta":{"output":[{"task_id":"task_combo"}]}}]}\n\n')],
        )

        with self.make_client(main_service_client=main_service_client, image_downloader=downloader) as client:
            response = client.post(
                "/videos",
                headers=self.auth_headers(),
                json={
                    "prompt": "combo",
                    "image_url": "https://example.com/input.png",
                    "references": ["s2ref_combo"],
                    "style": "cinematic",
                    "model": "sora-2-pro-portrait-10s",
                },
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            captured_requests[0],
            {
                "model": "sora2pro-portrait-10s",
                "messages": [{"role": "user", "content": "combo"}],
                "stream": True,
                "image": "combo-base64",
                "references": ["s2ref_combo"],
                "style": "cinematic",
            },
        )

    def test_create_rejects_unknown_model(self):
        with self.make_client() as client:
            response = client.post(
                "/videos",
                headers=self.auth_headers(),
                json={"prompt": "hello", "model": "unknown-model"},
            )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "unsupported_model")

    def test_create_rejects_invalid_bearer(self):
        with self.make_client() as client:
            response = client.post(
                "/videos",
                headers={"Authorization": "Bearer wrong"},
                json={"prompt": "hello"},
            )

        self.assertEqual(response.status_code, 401)

    def test_create_reference_validation_errors(self):
        insert_reference(self.db_path, "s2ref_ok")
        with self.make_client() as client:
            cases = [
                ({"prompt": "hello", "references": "bad"}, 400),
                ({"prompt": "hello", "references": [""]}, 400),
                ({"prompt": "hello", "references": ["https://example.com/ref"]}, 400),
                ({"prompt": "hello", "references": ["missing"]}, 400),
                ({"prompt": "hello", "references": ["a", "b", "c", "d", "e", "f"]}, 400),
            ]

            for payload, expected_status in cases:
                with self.subTest(payload=payload):
                    response = client.post("/videos", headers=self.auth_headers(), json=payload)
                    self.assertEqual(response.status_code, expected_status)

    def test_create_returns_gateway_timeout_when_task_id_is_delayed(self):
        main_service_client = build_main_service_client(
            chunks=[(0.2, b'data: {"choices":[{"delta":{"content":null}}]}\n\n')],
        )

        with self.make_client(main_service_client=main_service_client) as client:
            response = client.post(
                "/videos",
                headers=self.auth_headers(),
                json={"prompt": "slow"},
            )

        self.assertEqual(response.status_code, 504)
        self.assertEqual(response.json()["error"]["code"], "task_id_timeout")

    def test_create_returns_bad_gateway_for_malformed_sse(self):
        main_service_client = build_main_service_client(chunks=[(0, b"data: not-json\n\n")])

        with self.make_client(main_service_client=main_service_client) as client:
            response = client.post(
                "/videos",
                headers=self.auth_headers(),
                json={"prompt": "broken"},
            )

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.json()["error"]["code"], "upstream_protocol_error")

    def test_get_generation_maps_statuses_and_fields(self):
        insert_task(self.db_path, task_id="task_pending", status="processing", progress=0)
        insert_task(self.db_path, task_id="task_processing", status="processing", progress=12)
        insert_task(
            self.db_path,
            task_id="task_success",
            status="completed",
            progress=100,
            result_urls='["https://cdn.example.com/video.mp4","https://cdn.example.com/video2.mp4"]',
            completed_at="2026-03-24 12:10:00",
        )
        insert_task(
            self.db_path,
            task_id="task_failed",
            status="failed",
            progress=55,
            error_message=None,
            completed_at="2026-03-24 12:11:00",
        )
        insert_request_log(self.db_path, "task_failed", '{"error":{"message":"upstream broke"}}')

        created_at_expected = int(datetime.fromisoformat("2026-03-24 12:00:00").timestamp())
        completed_at_expected = int(datetime.fromisoformat("2026-03-24 12:10:00").timestamp())

        with self.make_client() as client:
            pending = client.get("/videos/generations/task_pending", headers=self.auth_headers())
            processing = client.get("/videos/generations/task_processing", headers=self.auth_headers())
            success = client.get("/videos/generations/task_success", headers=self.auth_headers())
            failed_first = client.get("/videos/generations/task_failed", headers=self.auth_headers())
            failed_second = client.get("/videos/generations/task_failed", headers=self.auth_headers())

        self.assertEqual(pending.status_code, 200)
        self.assertEqual(pending.json()["status"], "pending")
        self.assertEqual(processing.json()["status"], "processing")
        self.assertEqual(success.json()["status"], "success")
        self.assertEqual(success.json()["video_url"], "https://cdn.example.com/video.mp4")
        self.assertEqual(success.json()["created_at"], created_at_expected)
        self.assertEqual(success.json()["completed_at"], completed_at_expected)
        self.assertEqual(failed_first.json()["status"], "failed")
        self.assertEqual(failed_first.json()["error_message"], "upstream broke")
        self.assertEqual(failed_first.json(), failed_second.json())

    def test_get_generation_returns_404_for_unknown_task(self):
        with self.make_client() as client:
            response = client.get("/videos/generations/missing", headers=self.auth_headers())

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"]["code"], "task_not_found")


if __name__ == "__main__":
    unittest.main()
