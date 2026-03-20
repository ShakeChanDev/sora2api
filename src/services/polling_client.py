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

    async def _record_task_event(
        self,
        task_id: str,
        token_id: int,
        event_type: str,
        stage: str,
        status: str,
        message: str,
        details: Optional[dict] = None,
        error_code: Optional[str] = None,
    ):
        await self.db.create_task_event(
            task_id=task_id,
            token_id=token_id,
            event_type=event_type,
            stage=stage,
            status=status,
            message=message,
            details=json.dumps(details, ensure_ascii=False) if details is not None else None,
            error_code=error_code,
            error_reason=message if error_code else None,
        )

    def _preferred_url(self, polling_context: Optional[PollingContext], fallback: str) -> str:
        if polling_context and polling_context.page_url:
            return polling_context.page_url
        if polling_context and polling_context.egress_binding and polling_context.egress_binding.page_url:
            return polling_context.egress_binding.page_url
        return fallback

    async def _resolve_video_proxy_url(self, token_id: int) -> str:
        proxy_url = None
        if self.proxy_manager and hasattr(self.proxy_manager, "get_video_proxy_url"):
            proxy_url = await self.proxy_manager.get_video_proxy_url(token_id)
        elif self.db:
            token = await self.db.get_token(token_id)
            proxy_url = token.proxy_url if token else None
        if not proxy_url:
            raise PollingClientError(
                "browser_proxy_binding_required",
                "Video polling requires token proxy_url synchronized from the browser profile",
            )
        return proxy_url

    def _build_headers(self, access_token: str, polling_context: Optional[PollingContext]) -> Dict[str, str]:
        token_value = polling_context.access_token if polling_context and polling_context.access_token else access_token
        headers: Dict[str, str] = {
            "Authorization": f"Bearer {token_value}",
            "Accept": "application/json",
        }
        if not polling_context:
            return headers
        if polling_context.cookie_header:
            headers["Cookie"] = polling_context.cookie_header
        if polling_context.user_agent:
            headers["User-Agent"] = polling_context.user_agent
        if polling_context.device_id:
            headers["oai-device-id"] = polling_context.device_id
        if polling_context.referer:
            headers["referer"] = polling_context.referer
        if polling_context.sec_fetch_site:
            headers["sec-fetch-site"] = polling_context.sec_fetch_site
        if polling_context.sec_fetch_mode:
            headers["sec-fetch-mode"] = polling_context.sec_fetch_mode
        if polling_context.sec_fetch_dest:
            headers["sec-fetch-dest"] = polling_context.sec_fetch_dest
        if polling_context.sec_ch_ua:
            headers["sec-ch-ua"] = polling_context.sec_ch_ua
        if polling_context.sec_ch_ua_mobile:
            headers["sec-ch-ua-mobile"] = polling_context.sec_ch_ua_mobile
        if polling_context.sec_ch_ua_platform:
            headers["sec-ch-ua-platform"] = polling_context.sec_ch_ua_platform
        return headers

    async def _refresh_once(self, task_id: str, token_id: int, preferred_url: str) -> PollingContext:
        await self._record_task_event(
            task_id,
            token_id,
            "polling_auth_refresh_attempt",
            "polling",
            "running",
            "polling auth context refresh started",
            {"preferred_url": preferred_url},
        )
        try:
            auth_context = await self.mutation_executor.refresh_polling_context(
                token_id=token_id,
                preferred_url=preferred_url,
                task_id=task_id,
                flow="sora_2_create_task",
            )
        except Exception as exc:
            await self._record_task_event(
                task_id,
                token_id,
                "polling_auth_refresh_failed",
                "polling",
                "error",
                f"polling auth context refresh failed: {exc}",
                {"preferred_url": preferred_url},
                error_code="polling_auth_refresh_failed",
            )
            raise PollingClientError("polling_auth_refresh_failed", f"Polling auth refresh failed: {exc}") from exc

        polling_context = auth_context.to_polling_context()
        await self.db.update_task_polling_context(
            task_id=task_id,
            polling_context=json.dumps(polling_context.to_dict(), ensure_ascii=False),
            auth_snapshot_id=auth_context.auth_context_hash,
        )
        await self._record_task_event(
            task_id,
            token_id,
            "polling_auth_refresh_succeeded",
            "polling",
            "success",
            "polling auth context refreshed",
            {
                "profile_id": polling_context.profile_id,
                "page_url": polling_context.page_url,
                "proxy_url_present": bool(polling_context.egress_binding.proxy_url) if polling_context.egress_binding else False,
            },
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
        polling_context: PollingContext,
        preferred_url: str,
        allow_refresh: bool,
        unauthorized_code: str,
        not_found_code: Optional[str] = None,
        started_event_type: Optional[str] = None,
        success_event_type: Optional[str] = None,
    ) -> Tuple[object, PollingContext]:
        proxy_url = await self._resolve_video_proxy_url(token_id)
        url = f"{self.base_url}{endpoint}"
        headers = self._build_headers(access_token, polling_context)
        if started_event_type:
            await self._record_task_event(
                task_id,
                token_id,
                started_event_type,
                stage,
                "running",
                f"{operation} request started",
                {"endpoint": endpoint},
            )
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
                        unauthorized_code=unauthorized_code,
                        not_found_code=not_found_code,
                        started_event_type=started_event_type,
                        success_event_type=success_event_type,
                    )
                raise PollingClientError(unauthorized_code, f"{operation} returned {response.status_code} after browser auth refresh")
            if not_found_code and response.status_code == 404:
                raise PollingClientError(not_found_code, f"{operation} returned 404")
            if response.status_code >= 400:
                raise PollingClientError("polling_request_failed", f"{operation} returned {response.status_code}: {str(payload)[:500]}")
            if success_event_type:
                await self._record_task_event(
                    task_id,
                    token_id,
                    success_event_type,
                    stage,
                    "success",
                    f"{operation} request succeeded",
                    {"endpoint": endpoint, "status_code": response.status_code},
                )
            return payload, polling_context
        except PollingClientError:
            raise
        except Exception as exc:
            debug_logger.log_warning(f"[PollingClient] {operation} task={task_id} failed: {exc}")
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
        polling_context: PollingContext,
    ) -> Tuple[list, PollingContext]:
        payload, updated_context = await self._request_json(
            operation="pending_v2",
            endpoint="/nf/pending/v2",
            token_id=token_id,
            access_token=access_token,
            task_id=task_id,
            stage="polling",
            polling_context=polling_context,
            preferred_url=self._preferred_url(polling_context, "https://sora.chatgpt.com/explore"),
            allow_refresh=True,
            unauthorized_code="polling_pending_unauthorized",
            started_event_type="pending_request",
        )
        if not isinstance(payload, list):
            raise PollingClientError("polling_request_failed", "pending_v2 returned a non-list payload")
        return payload, updated_context

    async def get_video_drafts(
        self,
        task_id: str,
        token_id: int,
        access_token: str,
        polling_context: PollingContext,
        limit: int = 15,
    ) -> Tuple[Dict[str, object], PollingContext]:
        payload, updated_context = await self._request_json(
            operation="drafts_lookup",
            endpoint=f"/project_y/profile/drafts/v2?limit={limit}",
            token_id=token_id,
            access_token=access_token,
            task_id=task_id,
            stage="drafts_lookup",
            polling_context=polling_context,
            preferred_url=self._preferred_url(polling_context, "https://sora.chatgpt.com/explore"),
            allow_refresh=True,
            unauthorized_code="polling_drafts_unauthorized",
            not_found_code="polling_drafts_not_found",
            started_event_type="drafts_lookup_started",
        )
        if not isinstance(payload, dict):
            raise PollingClientError("polling_drafts_schema_invalid", "drafts_v2 returned a non-object payload")
        items = payload.get("items")
        if not isinstance(items, list):
            raise PollingClientError("polling_drafts_schema_invalid", "drafts_v2 payload missing items list")
        return payload, updated_context
