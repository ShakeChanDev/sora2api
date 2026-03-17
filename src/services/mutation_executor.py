"""Mutation strategy executor for page-bound Sora requests."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from ..core.config import config
from ..core.logger import debug_logger
from .browser_provider import (
    AuthContext,
    BrowserMutationRequest,
    BrowserProvider,
    BrowserProviderError,
)
from .browser_runtime import BrowserRuntime


class MutationStrategy:
    """Supported mutation strategies."""

    PAGE_EXECUTE = "page_execute"
    PAGE_REFRESH_THEN_REPLAY = "page_refresh_then_replay"
    REPLAY_WITH_PAGE_FALLBACK = "replay_with_page_fallback"
    REPLAY_ONLY = "replay_only"


class MutationType:
    """Known mutation types."""

    IMAGE_UPLOAD = "image_upload"
    IMAGE_SUBMIT = "image_submit"
    VIDEO_SUBMIT = "video_submit"
    STORYBOARD_SUBMIT = "storyboard_submit"
    REMIX_SUBMIT = "remix_submit"
    LONG_VIDEO_EXTENSION = "long_video_extension"
    PUBLISH_EXECUTE = "publish_execute"


@dataclass(frozen=True)
class MutationPolicy:
    """Execution policy for a mutation type."""

    default_strategy: str
    preferred_url: str
    flow: str
    allow_replay: bool = False


POLICIES: Dict[str, MutationPolicy] = {
    MutationType.VIDEO_SUBMIT: MutationPolicy(
        default_strategy=MutationStrategy.PAGE_EXECUTE,
        preferred_url="https://sora.chatgpt.com/explore",
        flow="sora_2_create_task",
    ),
    MutationType.STORYBOARD_SUBMIT: MutationPolicy(
        default_strategy=MutationStrategy.PAGE_EXECUTE,
        preferred_url="https://sora.chatgpt.com/explore",
        flow="sora_2_create_task",
    ),
    MutationType.REMIX_SUBMIT: MutationPolicy(
        default_strategy=MutationStrategy.PAGE_EXECUTE,
        preferred_url="https://sora.chatgpt.com/explore",
        flow="sora_2_create_task",
    ),
    MutationType.LONG_VIDEO_EXTENSION: MutationPolicy(
        default_strategy=MutationStrategy.PAGE_EXECUTE,
        preferred_url="https://sora.chatgpt.com/drafts",
        flow="sora_2_create_task",
    ),
    MutationType.PUBLISH_EXECUTE: MutationPolicy(
        default_strategy=MutationStrategy.PAGE_EXECUTE,
        preferred_url="https://sora.chatgpt.com/drafts",
        flow="sora_2_create_post",
    ),
}


RECOVERABLE_BROWSER_CODES = {"TARGET_CLOSED", "ECONNREFUSED", "execution_context_destroyed"}


class MutationExecutor:
    """Executes high-risk mutations with page-bound auth refresh and locking."""

    def __init__(self, db, provider: Optional[BrowserProvider], runtime: Optional[BrowserRuntime] = None):
        self.db = db
        self.provider = provider
        self.runtime = runtime or BrowserRuntime()

    def _get_policy(self, mutation_type: str) -> MutationPolicy:
        policy = POLICIES.get(mutation_type)
        if policy is None:
            raise ValueError(f"Unsupported mutation type: {mutation_type}")
        return policy

    async def _resolve_profile(self, token_id: Optional[int]) -> Tuple[str, str]:
        if not config.browser_enabled:
            raise BrowserProviderError("browser_provider_unavailable", "Browser-backed high-risk mutations are disabled in configuration")
        token_obj = await self.db.get_token(token_id) if token_id else None
        provider_name = (token_obj.browser_provider if token_obj and token_obj.browser_provider else config.browser_provider).strip() or "nst"
        profile_id = ""
        if token_obj and token_obj.browser_profile_id:
            profile_id = token_obj.browser_profile_id
        elif config.browser_default_profile_id:
            profile_id = config.browser_default_profile_id
        if not profile_id:
            raise BrowserProviderError("browser_profile_not_configured", "No browser profile bound to token and no default browser profile configured")
        if not self.provider or provider_name != getattr(self.provider, "provider_name", provider_name):
            raise BrowserProviderError("browser_provider_unavailable", f"Browser provider '{provider_name}' is not configured")
        return profile_id, provider_name

    async def _record_task_event(
        self,
        task_id: Optional[str],
        token_id: Optional[int],
        event_type: str,
        stage: Optional[str],
        status: str,
        message: str,
        details: Optional[dict] = None,
        error_code: Optional[str] = None,
    ):
        payload = json.dumps(details, ensure_ascii=False) if details is not None else None
        await self.db.create_task_event(
            task_id=task_id,
            token_id=token_id,
            event_type=event_type,
            stage=stage,
            status=status,
            message=message,
            details=payload,
            error_code=error_code,
            error_reason=message if error_code else None,
        )

    async def _record_failure(
        self,
        task_id: Optional[str],
        token_id: Optional[int],
        mutation_type: str,
        stage: str,
        error_code: str,
        message: str,
        details: Optional[dict] = None,
    ):
        await self.db.create_error_attribution(
            task_id=task_id,
            token_id=token_id,
            mutation_type=mutation_type,
            stage=stage,
            error_code=error_code,
            error_reason=message,
            details=json.dumps(details, ensure_ascii=False) if details is not None else None,
        )
        await self._record_task_event(
            task_id=task_id,
            token_id=token_id,
            event_type="error",
            stage=stage,
            status="error",
            message=message,
            details=details,
            error_code=error_code,
        )
        if task_id:
            await self.db.update_task_stage(
                task_id=task_id,
                current_stage=stage,
                failure_stage=stage,
                error_code=error_code,
                error_category="browser_mutation",
            )
        if token_id:
            await self.db.update_token_browser_state(
                token_id=token_id,
                last_auth_result="failed" if stage == "auth_refresh" else None,
                last_auth_error_reason=message if stage == "auth_refresh" else None,
                last_challenge_reason=message if error_code == "cloudflare_challenge" else None,
                account_status="auth_error" if stage == "auth_refresh" else None,
            )

    async def _persist_auth_context(self, token_id: Optional[int], auth_context: AuthContext):
        if not token_id:
            return
        await self.db.update_token(token_id, token=auth_context.access_token)
        await self.db.update_token_browser_state(
            token_id=token_id,
            browser_provider=auth_context.provider,
            browser_profile_id=auth_context.profile_id,
            sora_available=True,
            account_status="ready",
            last_auth_refresh_at=auth_context.refreshed_at,
            last_auth_result="success",
            last_auth_error_reason="",
            last_challenge_reason="",
            last_browser_user_agent=auth_context.user_agent,
            last_device_id=auth_context.device_id,
            last_egress_binding=auth_context.egress_binding.binding_key,
            last_auth_context_hash=auth_context.auth_context_hash,
            last_auth_context_expires_at=auth_context.expires_at,
            last_auth_page_url=auth_context.page_url,
        )

    def _failure_stage_for_code(self, error_code: str) -> str:
        """Map a browser/provider error code to a task stage."""
        if error_code in {"auth_context_incomplete", "auth_context_invalid", "sentinel_not_ready"}:
            return "auth_refresh"
        if error_code in {"cloudflare_challenge", "browser_context_missing", "browser_profile_not_configured", "browser_provider_unavailable"}:
            return "readiness"
        if error_code in {"TARGET_CLOSED", "ECONNREFUSED", "execution_context_destroyed"}:
            return "reconnect"
        return "mutation_submit"

    async def _run_page_plan(
        self,
        mutation_type: str,
        token_id: Optional[int],
        request_plan: List[BrowserMutationRequest],
        task_id: Optional[str] = None,
        preferred_url: Optional[str] = None,
    ) -> dict:
        policy = self._get_policy(mutation_type)
        profile_id, provider_name = await self._resolve_profile(token_id)
        preferred_url = preferred_url or policy.preferred_url

        attempt_id = await self.db.create_mutation_attempt(
            token_id=token_id,
            task_id=task_id,
            mutation_type=mutation_type,
            strategy=policy.default_strategy,
            stage="queued",
            status="started",
            provider=provider_name,
            profile_id=profile_id,
            window_id=None,
            page_url=preferred_url,
            egress_binding=None,
            details=json.dumps({"request_count": len(request_plan)}, ensure_ascii=False),
        )
        await self._record_task_event(task_id, token_id, "mutation_attempt", "queued", "started", f"{mutation_type} queued", {"profile_id": profile_id})

        last_response = None
        recovered = False

        async with self.runtime.profile_lock(profile_id):
            while True:
                connection = None
                try:
                    async with self.runtime.startup_queue():
                        await self.db.update_mutation_attempt(attempt_id, stage="startup", status="running")
                        connection = await self.provider.connect_profile(profile_id, preferred_url=preferred_url)

                    page_context = await self.provider.readiness_check(connection, preferred_url=preferred_url)
                    window_lock_key = f"{profile_id}:{page_context.page_id or page_context.page_url}"

                    async with self.runtime.window_lock(window_lock_key):
                        await self.db.update_mutation_attempt(
                            attempt_id,
                            stage="readiness",
                            status="running",
                            window_id=page_context.page_id,
                            page_url=page_context.page_url,
                        )
                        await self._record_task_event(task_id, token_id, "readiness", "readiness", "success", "page ready", {"page_url": page_context.page_url})

                        auth_context = await self.provider.refresh_auth_context(connection, policy.flow, preferred_url=preferred_url)
                        await self.db.update_mutation_attempt(
                            attempt_id,
                            stage="auth_refresh",
                            status="running",
                            egress_binding=auth_context.egress_binding.binding_key,
                            page_url=auth_context.page_url,
                        )
                        await self._persist_auth_context(token_id, auth_context)
                        await self._record_task_event(
                            task_id,
                            token_id,
                            "auth_refresh",
                            "auth_refresh",
                            "success",
                            "page auth context refreshed",
                            {
                                "profile_id": auth_context.profile_id,
                                "egress_binding": auth_context.egress_binding.binding_key,
                                "same_network_identity_proven": auth_context.egress_binding.same_network_identity_proven,
                            },
                        )

                        for index, request in enumerate(request_plan, start=1):
                            await self.db.update_mutation_attempt(attempt_id, stage="mutation_submit", status="running")
                            last_response = await self.provider.fetch_json(connection, request, auth_context)
                            await self._record_task_event(
                                task_id,
                                token_id,
                                "mutation_submit",
                                "mutation_submit",
                                "success",
                                f"{request.method} {request.url} completed",
                                {"index": index, "status": last_response.status},
                            )

                        response_data = last_response.data or {}
                        derived_task_id = response_data.get("id") or task_id
                        await self.db.update_mutation_attempt(
                            attempt_id,
                            task_id=derived_task_id,
                            stage="completed",
                            status="succeeded",
                            details=json.dumps({"status": last_response.status}, ensure_ascii=False),
                        )
                        return response_data

                except BrowserProviderError as exc:
                    error_details = {"mutation_type": mutation_type, "profile_id": profile_id, "recovered": recovered}
                    if attempt_id:
                        await self.db.update_mutation_attempt(
                            attempt_id,
                            stage="failed",
                            status="failed",
                            error_code=exc.code,
                            error_reason=str(exc),
                            details=json.dumps(error_details, ensure_ascii=False),
                        )
                    await self._record_failure(task_id, token_id, mutation_type, self._failure_stage_for_code(exc.code), exc.code, str(exc), error_details)
                    if exc.code in RECOVERABLE_BROWSER_CODES and not recovered:
                        recovered = True
                        await self._record_task_event(task_id, token_id, "reconnect", "reconnect", "running", f"Recovering browser profile after {exc.code}", {"profile_id": profile_id})
                        debug_logger.log_warning(f"[MutationExecutor] Recovering profile {profile_id} after {exc.code}: {exc}")
                        if connection:
                            await self.provider.disconnect(connection)
                        continue
                    raise
                finally:
                    if connection:
                        await self.provider.disconnect(connection)

    async def execute_video_submit(
        self,
        prompt: str,
        token_id: Optional[int],
        orientation: str,
        n_frames: int,
        model: str,
        size: str,
        media_id: Optional[str] = None,
        style_id: Optional[str] = None,
    ) -> str:
        inpaint_items = []
        if media_id:
            inpaint_items = [{"kind": "upload", "upload_id": media_id}]
        json_body = {
            "kind": "video",
            "prompt": prompt,
            "title": None,
            "orientation": orientation,
            "size": size,
            "n_frames": n_frames,
            "inpaint_items": inpaint_items,
            "remix_target_id": None,
            "reroll_target_id": None,
            "project_config": None,
            "trim_config": None,
            "metadata": None,
            "cameo_ids": None,
            "cameo_replacements": None,
            "model": model,
            "style_id": style_id,
            "audio_caption": None,
            "audio_transcript": None,
            "video_caption": None,
            "storyboard_id": None,
        }
        response = await self._run_page_plan(
            mutation_type=MutationType.VIDEO_SUBMIT,
            token_id=token_id,
            request_plan=[
                BrowserMutationRequest(
                    method="POST",
                    url="https://sora.chatgpt.com/backend/nf/create",
                    json_body=json_body,
                    expected_status=200,
                )
            ],
        )
        task_id = response.get("id")
        if not task_id:
            raise BrowserProviderError("page_execute_failed", "Video submit completed without task id")
        return task_id

    async def execute_storyboard_submit(
        self,
        prompt: str,
        token_id: Optional[int],
        orientation: str,
        media_id: Optional[str],
        n_frames: int,
        style_id: Optional[str],
    ) -> str:
        inpaint_items = [{"kind": "upload", "upload_id": media_id}] if media_id else []
        json_body = {
            "kind": "video",
            "prompt": prompt,
            "title": "Draft your video",
            "orientation": orientation,
            "size": "small",
            "n_frames": n_frames,
            "storyboard_id": None,
            "inpaint_items": inpaint_items,
            "remix_target_id": None,
            "reroll_target_id": None,
            "project_config": None,
            "trim_config": None,
            "model": "sy_8",
            "metadata": None,
            "style_id": style_id,
            "cameo_ids": None,
            "cameo_replacements": None,
            "audio_caption": None,
            "audio_transcript": None,
            "video_caption": None,
        }
        response = await self._run_page_plan(
            mutation_type=MutationType.STORYBOARD_SUBMIT,
            token_id=token_id,
            request_plan=[
                BrowserMutationRequest(
                    method="POST",
                    url="https://sora.chatgpt.com/backend/nf/create/storyboard",
                    json_body=json_body,
                    expected_status=200,
                )
            ],
        )
        task_id = response.get("id")
        if not task_id:
            raise BrowserProviderError("page_execute_failed", "Storyboard submit completed without task id")
        return task_id

    async def execute_remix_submit(
        self,
        remix_target_id: str,
        prompt: str,
        token_id: Optional[int],
        orientation: str,
        n_frames: int,
        style_id: Optional[str],
    ) -> str:
        json_body = {
            "kind": "video",
            "prompt": prompt,
            "title": None,
            "orientation": orientation,
            "size": "small",
            "n_frames": n_frames,
            "inpaint_items": [],
            "remix_target_id": remix_target_id,
            "reroll_target_id": None,
            "project_config": None,
            "trim_config": None,
            "metadata": None,
            "cameo_ids": None,
            "cameo_replacements": None,
            "model": "sy_8",
            "style_id": style_id,
            "audio_caption": None,
            "audio_transcript": None,
            "video_caption": None,
            "storyboard_id": None,
        }
        response = await self._run_page_plan(
            mutation_type=MutationType.REMIX_SUBMIT,
            token_id=token_id,
            request_plan=[
                BrowserMutationRequest(
                    method="POST",
                    url="https://sora.chatgpt.com/backend/nf/create",
                    json_body=json_body,
                    expected_status=200,
                )
            ],
        )
        task_id = response.get("id")
        if not task_id:
            raise BrowserProviderError("page_execute_failed", "Remix submit completed without task id")
        return task_id

    async def execute_long_video_extension(
        self,
        generation_id: str,
        prompt: str,
        extension_duration_s: int,
        token_id: Optional[int],
    ) -> str:
        response = await self._run_page_plan(
            mutation_type=MutationType.LONG_VIDEO_EXTENSION,
            token_id=token_id,
            preferred_url=f"https://sora.chatgpt.com/d/{generation_id}",
            request_plan=[
                BrowserMutationRequest(
                    method="POST",
                    url=f"https://sora.chatgpt.com/backend/project_y/profile/drafts/{generation_id}/long_video_extension",
                    json_body={
                        "user_prompt": prompt,
                        "extension_duration_s": extension_duration_s,
                        "enable_rewrite": True,
                    },
                    expected_status=200,
                )
            ],
        )
        task_id = response.get("id")
        if not task_id:
            raise BrowserProviderError("page_execute_failed", "Long video extension completed without task id")
        return task_id

    async def execute_publish(
        self,
        generation_id: str,
        post_text: str,
        token_id: Optional[int],
    ) -> str:
        response = await self._run_page_plan(
            mutation_type=MutationType.PUBLISH_EXECUTE,
            token_id=token_id,
            preferred_url=f"https://sora.chatgpt.com/d/{generation_id}",
            request_plan=[
                BrowserMutationRequest(
                    method="POST",
                    url=f"https://sora.chatgpt.com/backend/project_y/profile/drafts/{generation_id}/read",
                    json_body={},
                    expected_status=200,
                ),
                BrowserMutationRequest(
                    method="POST",
                    url="https://sora.chatgpt.com/backend/project_y/post",
                    json_body={
                        "attachments_to_create": [{"generation_id": generation_id, "kind": "sora"}],
                        "post_text": post_text,
                    },
                    expected_status=200,
                ),
            ],
        )
        post_id = response.get("post", {}).get("id", "")
        if not post_id:
            raise BrowserProviderError("page_execute_failed", "Publish completed without post id")
        return post_id
