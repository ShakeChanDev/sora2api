"""HTTP client for the main Sora2Api service."""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

import httpx

from .errors import AdapterError


@dataclass
class UpstreamVideoSession:
    """Live upstream SSE session that yields task_id asynchronously while draining."""

    response: httpx.Response
    line_iterator: AsyncIterator[str]
    request_id: str
    logger: logging.Logger
    task_id_wait_seconds: float
    _task_id_future: asyncio.Future[str] = field(init=False, repr=False)
    _timed_out_waiter: bool = field(default=False, init=False, repr=False)

    def __post_init__(self) -> None:
        self._task_id_future = asyncio.get_running_loop().create_future()

    async def wait_for_task_id(self) -> str:
        try:
            return await asyncio.wait_for(
                asyncio.shield(self._task_id_future),
                timeout=self.task_id_wait_seconds,
            )
        except asyncio.TimeoutError as exc:
            self._timed_out_waiter = True
            raise AdapterError(
                status_code=504,
                message="Timed out waiting for task_id from main service",
                error_type="gateway_timeout",
                code="task_id_timeout",
            ) from exc

    async def drain(self) -> None:
        self.logger.info("request_id=%s drain_started", self.request_id)
        try:
            async for line in self.line_iterator:
                payload_text = _extract_sse_data(line)
                if payload_text is None:
                    continue

                if payload_text == "[DONE]":
                    if not self._task_id_future.done():
                        self._task_id_future.set_exception(
                            AdapterError(
                                status_code=502,
                                message="Main service stream ended before task_id was returned",
                                error_type="bad_gateway",
                                code="upstream_protocol_error",
                            )
                        )
                    self.logger.info("request_id=%s drain_done", self.request_id)
                    return

                try:
                    chunk = json.loads(payload_text)
                except json.JSONDecodeError as exc:
                    protocol_error = AdapterError(
                        status_code=502,
                        message="Main service returned malformed SSE payload",
                        error_type="bad_gateway",
                        code="upstream_protocol_error",
                    )
                    if not self._task_id_future.done():
                        self._task_id_future.set_exception(protocol_error)
                        return
                    self.logger.warning("request_id=%s ignoring_malformed_sse_after_task_id=%s", self.request_id, exc)
                    continue

                if isinstance(chunk, dict) and "error" in chunk:
                    upstream_error = _classify_upstream_payload(chunk)
                    if not self._task_id_future.done():
                        self._task_id_future.set_exception(upstream_error)
                        return
                    self.logger.warning(
                        "request_id=%s upstream_error_after_task_id=%s",
                        self.request_id,
                        upstream_error.message,
                    )
                    continue

                task_id = _extract_task_id(chunk)
                if task_id and not self._task_id_future.done():
                    if self._timed_out_waiter:
                        self.logger.warning(
                            "request_id=%s task_id=%s arrived_after_timeout",
                            self.request_id,
                            task_id,
                        )
                    else:
                        self.logger.info(
                            "request_id=%s task_id=%s task_id_received",
                            self.request_id,
                            task_id,
                        )
                    self._task_id_future.set_result(task_id)

            if not self._task_id_future.done():
                self._task_id_future.set_exception(
                    AdapterError(
                        status_code=502,
                        message="Main service stream ended before task_id was returned",
                        error_type="bad_gateway",
                        code="upstream_protocol_error",
                    )
                )
            self.logger.warning("request_id=%s drain_eof_before_done", self.request_id)
        except asyncio.CancelledError:
            if not self._task_id_future.done():
                self._task_id_future.set_exception(
                    AdapterError(
                        status_code=502,
                        message="Main service stream was cancelled before task_id was returned",
                        error_type="bad_gateway",
                        code="upstream_stream_error",
                    )
                )
            self.logger.info("request_id=%s drain_cancelled", self.request_id)
            raise
        except AdapterError as exc:
            if not self._task_id_future.done():
                self._task_id_future.set_exception(exc)
            else:
                self.logger.warning("request_id=%s drain_error=%s", self.request_id, exc)
        except Exception as exc:
            if not self._task_id_future.done():
                self._task_id_future.set_exception(
                    AdapterError(
                        status_code=502,
                        message=f"Main service stream failed: {exc}",
                        error_type="bad_gateway",
                        code="upstream_stream_error",
                    )
                )
            else:
                self.logger.warning("request_id=%s drain_error=%s", self.request_id, exc)
        finally:
            await self.response.aclose()


class MainServiceClient:
    """HTTP/SSE bridge into the main service."""

    def __init__(
        self,
        base_url: str,
        task_id_wait_seconds: float,
        connect_timeout_seconds: float = 10.0,
        http_client: httpx.AsyncClient | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.task_id_wait_seconds = task_id_wait_seconds
        self.logger = logging.getLogger("polo_adapter.main_service")
        self._http_client = http_client or httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(
                connect=connect_timeout_seconds,
                read=None,
                write=connect_timeout_seconds,
                pool=connect_timeout_seconds,
            ),
        )

    async def close(self) -> None:
        await self._http_client.aclose()

    async def create_video_session(
        self,
        *,
        authorization_header: str,
        payload: dict[str, Any],
        request_id: str,
    ) -> UpstreamVideoSession:
        request = self._http_client.build_request(
            "POST",
            "/v1/chat/completions",
            headers={
                "Authorization": authorization_header,
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
            },
            json=payload,
        )

        try:
            response = await self._http_client.send(request, stream=True)
        except httpx.HTTPError as exc:
            raise AdapterError(
                status_code=502,
                message=f"Failed to call main service: {exc}",
                error_type="bad_gateway",
                code="main_service_unavailable",
            ) from exc

        if response.status_code != 200:
            try:
                body_text = await response.aread()
                decoded = body_text.decode("utf-8", errors="replace")
            finally:
                await response.aclose()
            raise _classify_non_stream_response(response.status_code, decoded)

        content_type = (response.headers.get("content-type") or "").lower()
        if "text/event-stream" not in content_type:
            try:
                body_text = await response.aread()
                decoded = body_text.decode("utf-8", errors="replace")
            finally:
                await response.aclose()
            raise _classify_non_stream_response(response.status_code, decoded)

        line_iterator = response.aiter_lines()
        return UpstreamVideoSession(
            response=response,
            line_iterator=line_iterator,
            request_id=request_id,
            logger=self.logger,
            task_id_wait_seconds=self.task_id_wait_seconds,
        )


def _extract_sse_data(line: str | None) -> str | None:
    if line is None:
        return None
    stripped = line.strip()
    if not stripped or not stripped.startswith("data:"):
        return None
    payload = stripped[5:].strip()
    return payload or None


def _extract_task_id(chunk: Any) -> str | None:
    if not isinstance(chunk, dict):
        return None
    choices = chunk.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    delta = choices[0].get("delta")
    if not isinstance(delta, dict):
        return None
    output = delta.get("output")
    if not isinstance(output, list) or not output:
        return None
    first_item = output[0]
    if not isinstance(first_item, dict):
        return None
    task_id = first_item.get("task_id")
    return task_id if isinstance(task_id, str) and task_id.strip() else None


def _extract_error_message(payload: Any) -> str:
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            message = error.get("message")
            if isinstance(message, str) and message.strip():
                return message.strip()
        detail = payload.get("detail")
        if isinstance(detail, str) and detail.strip():
            return detail.strip()
    if isinstance(payload, str) and payload.strip():
        return payload.strip()
    return "Main service returned an unexpected error"


def _is_classified_input_error(message: str) -> bool:
    lowered = message.lower()
    return any(
        token in lowered
        for token in (
            "invalid model",
            "unsupported model",
            "references ",
            "reference ",
            "messages cannot be empty",
        )
    )


def _classify_upstream_payload(payload: Any) -> AdapterError:
    message = _extract_error_message(payload)
    if _is_classified_input_error(message):
        return AdapterError(
            status_code=400,
            message=message,
            error_type="invalid_request_error",
            code="main_service_validation_error",
        )
    return AdapterError(
        status_code=502,
        message=message,
        error_type="bad_gateway",
        code="main_service_error",
    )


def _classify_non_stream_response(status_code: int, body_text: str) -> AdapterError:
    message = body_text.strip()
    try:
        parsed = json.loads(body_text)
        message = _extract_error_message(parsed)
    except json.JSONDecodeError:
        if not message:
            message = f"Main service returned HTTP {status_code}"

    if status_code in {400, 422} and _is_classified_input_error(message):
        return AdapterError(
            status_code=400,
            message=message,
            error_type="invalid_request_error",
            code="main_service_validation_error",
        )

    return AdapterError(
        status_code=502,
        message=message,
        error_type="bad_gateway",
        code="main_service_error",
    )
