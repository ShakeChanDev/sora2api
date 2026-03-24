from __future__ import annotations

import asyncio
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from polo_adapter.app.api import AdapterServices
from polo_adapter.app.main import create_app
from polo_adapter.app.main_service_client import MainServiceError
from polo_adapter.app.settings import Settings


class FakeRepo:
    def __init__(self, reference_ids=None, tasks=None, logs=None, api_key="han1234"):
        self.reference_ids = set(reference_ids or [])
        self.tasks = tasks or {}
        self.logs = logs or {}
        self.api_key = api_key

    async def validate_shared_api_key(self, expected_api_key: str) -> None:
        if expected_api_key != self.api_key:
            raise RuntimeError("api key mismatch")

    async def get_reference_ids(self, reference_ids):
        return set(reference_ids) & self.reference_ids

    async def get_task(self, task_id: str):
        return self.tasks.get(task_id)

    async def get_latest_request_log(self, task_id: str):
        return self.logs.get(task_id)


class FakeDownloader:
    def __init__(self, base64_value="aW1hZ2U=", error: Exception | None = None):
        self.base64_value = base64_value
        self.error = error
        self.urls = []

    async def download_as_base64(self, url: str) -> str:
        self.urls.append(url)
        if self.error:
            raise self.error
        return self.base64_value

    async def aclose(self) -> None:
        return None


class FakeStream:
    def __init__(self, lines):
        self.lines = lines
        self.closed = False
        self.completed = asyncio.Event()

    async def aiter_lines(self):
        try:
            for item in self.lines:
                delay = 0.0
                text = item
                if isinstance(item, tuple):
                    delay, text = item
                if delay:
                    await asyncio.sleep(delay)
                yield text
        finally:
            self.completed.set()

    async def aclose(self) -> None:
        self.closed = True
        self.completed.set()


class FakeMainServiceClient:
    def __init__(self, stream=None, error: Exception | None = None):
        self.stream = stream
        self.error = error
        self.calls = []

    async def start_create_stream(self, payload: dict, bearer: str):
        self.calls.append({"payload": payload, "bearer": bearer})
        if self.error:
            raise self.error
        return self.stream

    async def aclose(self) -> None:
        return None


def build_settings(**overrides) -> Settings:
    base = {
        "shared_api_key": "han1234",
        "main_base_url": "http://127.0.0.1:8000",
        "db_path": "data/hancat.db",
        "adapter_host": "0.0.0.0",
        "adapter_port": 8010,
        "create_timeout_seconds": 5.0,
        "image_download_timeout_seconds": 10.0,
        "image_max_bytes": 10 * 1024 * 1024,
        "image_max_redirects": 3,
        "main_local_tz": "Asia/Shanghai",
    }
    base.update(overrides)
    return Settings(**base)


def make_services(settings: Settings, repo=None, downloader=None, main_client=None) -> AdapterServices:
    return AdapterServices(
        settings=settings,
        repo=repo or FakeRepo(api_key=settings.shared_api_key),
        image_downloader=downloader or FakeDownloader(),
        main_service_client=main_client or FakeMainServiceClient(),
    )


def sse_event(payload: str) -> list[str]:
    return [f"data: {payload}", ""]


@asynccontextmanager
async def open_test_client(app):
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            yield client


@pytest.mark.asyncio
async def test_create_text_video_success_returns_id_and_default_model():
    stream = FakeStream(sse_event('{"choices":[{"delta":{"output":[{"task_id":"task_1"}]}}]}') + sse_event("[DONE]"))
    settings = build_settings()
    services = make_services(settings, main_client=FakeMainServiceClient(stream=stream))
    app = create_app(settings=settings, services=services)

    async with open_test_client(app) as client:
        response = await client.post("/videos", json={"prompt": "hello"}, headers={"Authorization": "Bearer han1234"})
    assert response.status_code == 200
    assert response.json() == {
        "id": "task_1",
        "object": "video.generation",
        "created": response.json()["created"],
        "model": "sora-2-portrait-15s",
        "status": "pending",
    }
    upstream_payload = services.main_service_client.calls[0]["payload"]
    assert upstream_payload["model"] == "sora2-portrait-15s"
    assert upstream_payload["messages"] == [{"role": "user", "content": "hello"}]
    assert upstream_payload["stream"] is True
    await asyncio.wait_for(stream.completed.wait(), timeout=0.2)


@pytest.mark.asyncio
async def test_create_with_image_references_and_style_passes_upstream_fields():
    stream = FakeStream(sse_event('{"choices":[{"delta":{"output":[{"task_id":"task_2"}]}}]}') + sse_event("[DONE]"))
    settings = build_settings()
    repo = FakeRepo(reference_ids={"ref_a", "ref_b"}, api_key=settings.shared_api_key)
    downloader = FakeDownloader(base64_value="ZmFrZS1pbWFnZQ==")
    main_client = FakeMainServiceClient(stream=stream)
    app = create_app(settings=settings, services=make_services(settings, repo=repo, downloader=downloader, main_client=main_client))

    async with open_test_client(app) as client:
        response = await client.post(
            "/videos",
            json={
                "prompt": "hello",
                "image_url": "https://example.com/image.png",
                "style": "anime",
                "references": ["ref_a", "ref_a", "ref_b"],
            },
            headers={"Authorization": "Bearer han1234"},
        )
    assert response.status_code == 200
    payload = main_client.calls[0]["payload"]
    assert payload["image"] == "ZmFrZS1pbWFnZQ=="
    assert payload["references"] == ["ref_a", "ref_b"]
    assert payload["style"] == "anime"
    assert downloader.urls == ["https://example.com/image.png"]


@pytest.mark.asyncio
async def test_create_unknown_model_returns_400():
    settings = build_settings()
    app = create_app(settings=settings, services=make_services(settings))
    async with open_test_client(app) as client:
        response = await client.post(
            "/videos",
            json={"prompt": "hello", "model": "bad-model"},
            headers={"Authorization": "Bearer han1234"},
        )
    assert response.status_code == 400
    assert response.json()["detail"] == "unsupported model: bad-model"


@pytest.mark.asyncio
async def test_create_invalid_bearer_returns_401():
    settings = build_settings()
    app = create_app(settings=settings, services=make_services(settings))
    async with open_test_client(app) as client:
        response = await client.post(
            "/videos",
            json={"prompt": "hello"},
            headers={"Authorization": "Bearer wrong"},
        )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_create_timeout_returns_504_and_worker_keeps_draining():
    stream = FakeStream([(0.05, 'data: {"choices":[{"delta":{"output":[{"task_id":"late_task"}]}}]}'), "", (0.01, "data: [DONE]"), ""])
    settings = build_settings(create_timeout_seconds=0.01)
    client = FakeMainServiceClient(stream=stream)
    app = create_app(settings=settings, services=make_services(settings, main_client=client))

    async with open_test_client(app) as client:
        response = await client.post(
            "/videos",
            json={"prompt": "slow"},
            headers={"Authorization": "Bearer han1234"},
        )
        assert response.status_code == 504
        await asyncio.wait_for(stream.completed.wait(), timeout=0.2)
        assert stream.closed is True


@pytest.mark.asyncio
async def test_create_malformed_sse_returns_502():
    stream = FakeStream(["data: not-json", ""])
    settings = build_settings()
    app = create_app(settings=settings, services=make_services(settings, main_client=FakeMainServiceClient(stream=stream)))

    async with open_test_client(app) as client:
        response = await client.post(
            "/videos",
            json={"prompt": "bad"},
            headers={"Authorization": "Bearer han1234"},
        )
    assert response.status_code == 502
    assert "malformed SSE JSON" in response.json()["detail"]


@pytest.mark.asyncio
async def test_create_non_sse_upstream_returns_502():
    settings = build_settings()
    error = MainServiceError("main service did not return text/event-stream")
    app = create_app(settings=settings, services=make_services(settings, main_client=FakeMainServiceClient(error=error)))

    async with open_test_client(app) as client:
        response = await client.post(
            "/videos",
            json={"prompt": "bad"},
            headers={"Authorization": "Bearer han1234"},
        )
    assert response.status_code == 502
    assert response.json()["detail"] == "main service did not return text/event-stream"


@pytest.mark.asyncio
async def test_references_validation_errors():
    settings = build_settings()
    repo = FakeRepo(reference_ids={"ref_a"}, api_key=settings.shared_api_key)
    app = create_app(settings=settings, services=make_services(settings, repo=repo))

    async with open_test_client(app) as client:
        response = await client.post(
            "/videos",
            json={"prompt": "hello", "references": ["", "ref_a"]},
            headers={"Authorization": "Bearer han1234"},
        )
        assert response.status_code == 400
        assert response.json()["detail"] == "references must be an array of strings"

        too_many = ["a", "b", "c", "d", "e", "f"]
        response = await client.post(
            "/videos",
            json={"prompt": "hello", "references": too_many},
            headers={"Authorization": "Bearer han1234"},
        )
        assert response.status_code == 400
        assert response.json()["detail"] == "references supports at most 5 unique ids"

        response = await client.post(
            "/videos",
            json={"prompt": "hello", "references": ["missing"]},
            headers={"Authorization": "Bearer han1234"},
        )
        assert response.status_code == 400
        assert response.json()["detail"] == "reference missing not found"


@pytest.mark.asyncio
async def test_references_must_be_array_returns_400():
    settings = build_settings()
    app = create_app(settings=settings, services=make_services(settings))
    async with open_test_client(app) as client:
        response = await client.post(
            "/videos",
            json={"prompt": "hello", "references": "bad"},
            headers={"Authorization": "Bearer han1234"},
        )
    assert response.status_code == 400
    assert response.json()["detail"] == "references must be an array of strings"


def create_sqlite_fixture_db(db_path: Path, api_key: str = "han1234") -> None:
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE admin_config (
            id INTEGER PRIMARY KEY,
            api_key TEXT NOT NULL
        );
        CREATE TABLE tasks (
            task_id TEXT PRIMARY KEY,
            status TEXT,
            progress FLOAT,
            result_urls TEXT,
            error_message TEXT,
            created_at TEXT,
            completed_at TEXT
        );
        CREATE TABLE request_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT,
            response_body TEXT,
            status_code INTEGER,
            created_at TEXT,
            updated_at TEXT
        );
        CREATE TABLE "references" (
            reference_id TEXT PRIMARY KEY
        );
        """
    )
    conn.execute("INSERT INTO admin_config (id, api_key) VALUES (1, ?)", (api_key,))
    conn.commit()
    conn.close()


@pytest.mark.asyncio
async def test_query_status_mapping_and_error_fallback(tmp_path: Path):
    db_path = tmp_path / "adapter.db"
    create_sqlite_fixture_db(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        INSERT INTO tasks (task_id, status, progress, result_urls, error_message, created_at, completed_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "task_ok",
            "completed",
            100,
            '["https://cdn.example.com/video.mp4"]',
            None,
            "2026-03-25 00:00:00",
            "2026-03-25 08:30:00",
        ),
    )
    conn.execute(
        """
        INSERT INTO tasks (task_id, status, progress, result_urls, error_message, created_at, completed_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "task_fail",
            "failed",
            80,
            None,
            None,
            "2026-03-25 01:00:00",
            "2026-03-25 09:00:00",
        ),
    )
    conn.execute(
        """
        INSERT INTO request_logs (task_id, response_body, status_code, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            "task_fail",
            '{"error":{"message":"upstream failed"}}',
            500,
            "2026-03-25 09:00:00",
            "2026-03-25 09:00:01",
        ),
    )
    conn.commit()
    conn.close()

    settings = build_settings(db_path=str(db_path))
    app = create_app(settings=settings)

    async with open_test_client(app) as client:
        ok_response = await client.get("/videos/generations/task_ok", headers={"Authorization": "Bearer han1234"})
        fail_response = await client.get("/videos/generations/task_fail", headers={"Authorization": "Bearer han1234"})
        again_response = await client.get("/videos/generations/task_fail", headers={"Authorization": "Bearer han1234"})
    assert ok_response.status_code == 200
    assert ok_response.json()["status"] == "success"
    assert ok_response.json()["video_url"] == "https://cdn.example.com/video.mp4"
    assert ok_response.json()["created_at"] == 1774396800
    assert ok_response.json()["completed_at"] == 1774398600

    assert fail_response.status_code == 200
    assert fail_response.json()["status"] == "failed"
    assert fail_response.json()["error_message"] == "upstream failed"

    assert again_response.json() == fail_response.json()


@pytest.mark.asyncio
async def test_query_pending_and_not_found(tmp_path: Path):
    db_path = tmp_path / "adapter.db"
    create_sqlite_fixture_db(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        INSERT INTO tasks (task_id, status, progress, result_urls, error_message, created_at, completed_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        ("task_pending", "processing", 0, None, None, "2026-03-25 02:00:00", None),
    )
    conn.execute(
        """
        INSERT INTO tasks (task_id, status, progress, result_urls, error_message, created_at, completed_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        ("task_processing", "processing", 42, None, None, "2026-03-25 03:00:00", None),
    )
    conn.commit()
    conn.close()

    settings = build_settings(db_path=str(db_path))
    app = create_app(settings=settings)

    async with open_test_client(app) as client:
        pending_response = await client.get("/videos/generations/task_pending", headers={"Authorization": "Bearer han1234"})
        processing_response = await client.get("/videos/generations/task_processing", headers={"Authorization": "Bearer han1234"})
        missing_response = await client.get("/videos/generations/task_missing", headers={"Authorization": "Bearer han1234"})
    assert pending_response.status_code == 200
    assert pending_response.json()["status"] == "pending"

    assert processing_response.status_code == 200
    assert processing_response.json()["status"] == "processing"

    assert missing_response.status_code == 404
