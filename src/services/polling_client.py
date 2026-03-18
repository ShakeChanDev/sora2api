"""Task-scoped polling client for steady-state Sora result retrieval."""
from __future__ import annotations

import json
import time
from typing import Dict, Optional, Tuple

from curl_cffi.requests import AsyncSession

from ..core.config import config
from ..core.logger import debug_logger
from .browser_provider import PollingContext


class PollingClientError(RuntimeError):
    """Polling failure with a structured code."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class PollingClient:
    """Server-side polling with task-scoped browser auth context."""

    def __init__(self, db, proxy_manager, mutation_executor, base_url: Optional[str] = None, timeout: Optional[int] = None):
        self.db = db
        self.proxy_manager = proxy_manager
        self.mutation_executor = mutation_executor
        self.base_url = (base_url or config.sora_base_url).rstrip("/")
        self.timeout = timeout or config.sora_timeout

    def _build_headers(self, access_token: str, polling_context: Optional[PollingContext]) -> Dict[str, str]:
        token_value = polling_context.access_token if polling_context and polling_context.access_token else access_token
        headers: Dict[str, str] = {
            "Authorization": f"Bearer {token_value}",
            "Accept": "application/json",
        }
        if polling_context:
            if polling_context.cookie_header:
                headers["Cookie"] = polling_context.cookie_header
            if polling_context.user_agent:
                headers["User-Agent"] = polling_context.user_agent
            if polling_context.device_id:
                headers["oai-device-id"] = polling_context.device_id
        return headers

    async def _refresh_once(self, task_id: str, token_id: int, preferred_url: str) -> PollingContext:
        auth_context = await self.mutation_executor.refresh_polling_context(
            token_id=token_id,
            preferred_url=preferred_url,
            task_id=task_id,
            flow="sora_2_create_task",
        )
        polling_context = auth_context.to_polling_context()
        await self.db.update_task_polling_context(
            task_id=task_id,
            polling_context=json.dumps(polling_context.to_dict(), ensure_ascii=False),
            auth_snapshot_id=auth_context.auth_context_hash,
        )
        return polling_context

    async def _request_json(
        self,
        operation: str,
        endpoint: str,
        token_id: int,
        access_token: str,
        task_id: str,
        stage: str,
        polling_context: Optional[PollingContext] = None,
        preferred_url: str = "https://sora.chatgpt.com/drafts",
        allow_refresh: bool = True,
    ) -> Tuple[object, Optional[PollingContext]]:
        proxy_url = await self.proxy_manager.get_proxy_url(token_id=token_id) if self.proxy_manager else None
        url = f"{self.base_url}{endpoint}"
        headers = self._build_headers(access_token, polling_context)
        started_at = time.time()
        try:
            async with AsyncSession(impersonate="chrome") as session:
                response = await session.get(
                    url,
                    headers=headers,
                    proxy=proxy_url,
                    timeout=self.timeout,
                )
            duration = time.time() - started_at
            try:
                payload = response.json()
            except Exception:
                payload = response.text
            debug_logger.log_info(
                f"[PollingClient] {operation} task={task_id} status={response.status_code} duration={duration:.2f}s"
            )
            if response.status_code in {401, 403}:
                if allow_refresh:
                    refreshed_context = await self._refresh_once(task_id, token_id, preferred_url)
                    return await self._request_json(
                        operation=operation,
                        endpoint=endpoint,
                        token_id=token_id,
                        access_token=access_token,
                        task_id=task_id,
                        stage=stage,
                        polling_context=refreshed_context,
                        preferred_url=preferred_url,
                        allow_refresh=False,
                    )
                raise PollingClientError("polling_auth_refresh_failed", f"{operation} returned {response.status_code} after browser auth refresh")
            if response.status_code >= 400:
                raise PollingClientError("polling_request_failed", f"{operation} returned {response.status_code}: {str(payload)[:500]}")
            return payload, polling_context
        except PollingClientError:
            raise
        except Exception as exc:
            debug_logger.log_warning(
                f"[PollingClient] {operation} task={task_id} failed: {exc}"
            )
            raise PollingClientError("polling_request_failed", str(exc)) from exc

    async def load_task_polling_context(self, task_id: str) -> Optional[PollingContext]:
        task = await self.db.get_task(task_id)
        if not task or not task.polling_context:
            return None
        try:
            return PollingContext.from_dict(json.loads(task.polling_context))
        except Exception as exc:
            debug_logger.log_warning(f"[PollingClient] Failed to load polling context for {task_id}: {exc}")
            return None

    async def get_pending_tasks(
        self,
        task_id: str,
        token_id: int,
        access_token: str,
        polling_context: Optional[PollingContext] = None,
    ) -> Tuple[list, Optional[PollingContext]]:
        payload, updated_context = await self._request_json(
            operation="pending_v2",
            endpoint="/nf/pending/v2",
            token_id=token_id,
            access_token=access_token,
            task_id=task_id,
            stage="polling",
            polling_context=polling_context,
            preferred_url="https://sora.chatgpt.com/drafts",
        )
        return payload if isinstance(payload, list) else [], updated_context

    async def get_video_drafts(
        self,
        task_id: str,
        token_id: int,
        access_token: str,
        polling_context: Optional[PollingContext] = None,
        limit: int = 15,
    ) -> Tuple[Dict[str, object], Optional[PollingContext]]:
        payload, updated_context = await self._request_json(
            operation="drafts_lookup",
            endpoint=f"/project_y/profile/drafts?limit={limit}",
            token_id=token_id,
            access_token=access_token,
            task_id=task_id,
            stage="drafts_lookup",
            polling_context=polling_context,
            preferred_url="https://sora.chatgpt.com/drafts",
        )
        return payload if isinstance(payload, dict) else {}, updated_context
