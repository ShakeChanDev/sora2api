import asyncio
import unittest

import httpx

from polo_adapter.app.errors import AdapterError
from polo_adapter.app.main_service_client import MainServiceClient


class ChunkStream(httpx.AsyncByteStream):
    def __init__(self, parts):
        self.parts = parts

    async def __aiter__(self):
        for part in self.parts:
            delay, payload = part
            if delay:
                await asyncio.sleep(delay)
            yield payload

    async def aclose(self):
        return None


class MainServiceClientTests(unittest.IsolatedAsyncioTestCase):
    async def test_extracts_task_id_and_drains(self):
        done_event = asyncio.Event()

        def handler(_request: httpx.Request) -> httpx.Response:
            class DoneStream(httpx.AsyncByteStream):
                async def __aiter__(self_inner):
                    stream = ChunkStream(
                        [
                            (0, b'data: {"choices":[{"delta":{"output":[{"task_id":"task_123"}]}}]}\n\n'),
                            (0, b'data: {"choices":[{"delta":{"content":null}}]}\n\n'),
                            (0, b"data: [DONE]\n\n"),
                        ]
                    )
                    async for chunk in stream:
                        if chunk == b"data: [DONE]\n\n":
                            done_event.set()
                        yield chunk

                async def aclose(self_inner):
                    done_event.set()
                    return None

            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                stream=DoneStream(),
            )

        async_client = httpx.AsyncClient(
            base_url="http://main.test",
            transport=httpx.MockTransport(handler),
        )
        client = MainServiceClient(
            base_url="http://main.test",
            task_id_wait_seconds=0.1,
            http_client=async_client,
        )

        session = await client.create_video_session(
            authorization_header="Bearer test-key",
            payload={"prompt": "hello"},
            request_id="req-1",
        )

        self.assertEqual(session.task_id, "task_123")
        await session.drain()
        self.assertTrue(done_event.is_set())
        await client.close()

    async def test_returns_timeout_when_task_id_is_not_emitted_in_time(self):
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                stream=ChunkStream([(0.2, b'data: {"choices":[{"delta":{"content":null}}]}\n\n')]),
            )

        async_client = httpx.AsyncClient(
            base_url="http://main.test",
            transport=httpx.MockTransport(handler),
        )
        client = MainServiceClient(
            base_url="http://main.test",
            task_id_wait_seconds=0.05,
            http_client=async_client,
        )

        with self.assertRaises(AdapterError) as ctx:
            await client.create_video_session(
                authorization_header="Bearer test-key",
                payload={"prompt": "hello"},
                request_id="req-2",
            )

        self.assertEqual(ctx.exception.status_code, 504)
        self.assertEqual(ctx.exception.code, "task_id_timeout")
        await client.close()

    async def test_rejects_malformed_sse_payload(self):
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                stream=ChunkStream([(0, b"data: not-json\n\n")]),
            )

        async_client = httpx.AsyncClient(
            base_url="http://main.test",
            transport=httpx.MockTransport(handler),
        )
        client = MainServiceClient(
            base_url="http://main.test",
            task_id_wait_seconds=0.05,
            http_client=async_client,
        )

        with self.assertRaises(AdapterError) as ctx:
            await client.create_video_session(
                authorization_header="Bearer test-key",
                payload={"prompt": "hello"},
                request_id="req-3",
            )

        self.assertEqual(ctx.exception.status_code, 502)
        self.assertEqual(ctx.exception.code, "upstream_protocol_error")
        await client.close()


if __name__ == "__main__":
    unittest.main()
