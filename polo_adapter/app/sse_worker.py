"""Background SSE consumer that extracts task_id and drains upstream to completion."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

from .main_service_client import MainServiceStream

logger = logging.getLogger(__name__)


class SSEProtocolError(RuntimeError):
    """Raised when the main service SSE protocol is invalid before task_id arrives."""


class MainServiceSSEWorker:
    """Consume the main-service SSE stream and expose the first task_id future."""

    def __init__(self, stream: MainServiceStream):
        self._stream = stream
        self._task_id_future: asyncio.Future[str] = asyncio.get_running_loop().create_future()
        self._drain_task: Optional[asyncio.Task] = None
        self._timed_out_waiter = False

    async def start(self) -> None:
        """Start draining the stream in the background."""

        if self._drain_task is None:
            self._drain_task = asyncio.create_task(self._drain(), name="polo-adapter-sse-drain")

    async def wait_for_task_id(self, timeout: float) -> str:
        """Wait for the first task_id emitted by the upstream stream."""

        try:
            return await asyncio.wait_for(asyncio.shield(self._task_id_future), timeout=timeout)
        except asyncio.TimeoutError:
            self._timed_out_waiter = True
            raise

    async def drain_to_end(self) -> None:
        """Wait until background stream consumption finishes."""

        if self._drain_task is not None:
            await self._drain_task

    async def _drain(self) -> None:
        buffered_lines: list[str] = []
        try:
            async for line in self._stream.aiter_lines():
                if line == "":
                    await self._handle_event(buffered_lines)
                    buffered_lines = []
                    continue
                if line.startswith(":"):
                    continue
                buffered_lines.append(line)

            if buffered_lines:
                await self._handle_event(buffered_lines)

            if not self._task_id_future.done():
                self._task_id_future.set_exception(
                    SSEProtocolError("main service stream ended before task_id was emitted")
                )
        except Exception as exc:
            if not self._task_id_future.done():
                self._task_id_future.set_exception(exc)
            else:
                logger.warning("Main service SSE drain failed after task_id: %s", exc)
        finally:
            await self._stream.aclose()

    async def _handle_event(self, lines: list[str]) -> None:
        if not lines:
            return

        data_lines = []
        for line in lines:
            if line.startswith("data:"):
                data_lines.append(line[5:].lstrip())

        if not data_lines:
            return

        payload_text = "\n".join(data_lines).strip()
        if not payload_text or payload_text == "[DONE]":
            return

        try:
            payload = json.loads(payload_text)
        except json.JSONDecodeError as exc:
            if not self._task_id_future.done():
                raise SSEProtocolError("main service emitted malformed SSE JSON before task_id") from exc
            logger.warning("Ignoring malformed SSE JSON after task_id: %s", payload_text)
            return

        if isinstance(payload, dict) and "error" in payload and not self._task_id_future.done():
            raise SSEProtocolError(self._extract_error_message(payload))

        task_id = self._extract_task_id(payload)
        if task_id and not self._task_id_future.done():
            if self._timed_out_waiter:
                logger.warning("task_id %s arrived after adapter already returned 504", task_id)
            self._task_id_future.set_result(task_id)

    @staticmethod
    def _extract_task_id(payload: object) -> Optional[str]:
        if not isinstance(payload, dict):
            return None
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            return None
        delta = choices[0].get("delta")
        if not isinstance(delta, dict):
            return None
        output = delta.get("output")
        if not isinstance(output, list) or not output:
            return None
        first = output[0]
        if not isinstance(first, dict):
            return None
        task_id = first.get("task_id")
        return task_id if isinstance(task_id, str) and task_id else None

    @staticmethod
    def _extract_error_message(payload: dict) -> str:
        error = payload.get("error")
        if isinstance(error, dict):
            message = error.get("message")
            if isinstance(message, str) and message.strip():
                return message.strip()
        if isinstance(error, str) and error.strip():
            return error.strip()
        return "main service returned an error before task_id"
