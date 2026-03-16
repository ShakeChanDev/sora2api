"""Page-backed auth-context refresh service."""
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import AsyncIterator

from ..core.database import Database
from ..core.logger import debug_logger
from ..core.models import Token
from .browser_provider import BrowserProvider
from .browser_runtime import AUTH_ERROR_CODES, AuthContext, BrowserAuthError, BrowserHandle, BrowserLockManager


@dataclass
class ManagedBrowserSession:
    """Lock-bound browser session used by a single high-risk mutation."""

    provider: BrowserProvider
    db: Database
    token: Token
    handle: BrowserHandle
    auth_context: AuthContext
    lock_manager: BrowserLockManager
    close_on_exit: bool = True

    async def execute_in_page(self, action: str, payload: dict) -> dict:
        return await self.provider.execute_in_page(self.handle, action, payload)

    async def refresh_auth_context(self, target_url: str, require_sentinel: bool = True) -> AuthContext:
        return await refresh_auth_context(
            self.provider,
            self.db,
            self.token,
            self.handle,
            target_url=target_url,
            require_sentinel=require_sentinel,
        )

    async def close(self):
        if self.close_on_exit:
            await self.provider.stop_profile(self.handle.profile_id)


async def _extract_auth_context(handle: BrowserHandle, provider: BrowserProvider, target_url: str, require_sentinel: bool) -> AuthContext:
    page_context = await provider.get_page_context(handle, target_url)
    page = handle.page

    session_payload = await page.evaluate(
        """async () => {
            const response = await fetch('/api/auth/session', { credentials: 'include' });
            const text = await response.text();
            let json = null;
            try {
                json = JSON.parse(text);
            } catch (_) {}
            return { ok: response.ok, status: response.status, text, json };
        }"""
    )

    if not session_payload.get("ok") or not session_payload.get("json"):
        raise BrowserAuthError(
            AUTH_ERROR_CODES["AUTH_CONTEXT_INVALID"],
            f"Failed to fetch /api/auth/session: status={session_payload.get('status')}",
            upstream_status=session_payload.get("status"),
        )

    access_token = session_payload["json"].get("accessToken")
    if not access_token:
        raise BrowserAuthError(
            AUTH_ERROR_CODES["AUTH_CONTEXT_INCOMPLETE"],
            "Session payload did not contain accessToken",
        )

    sentinel_token = None
    sentinel_ready = False
    if require_sentinel:
        sentinel_ready = await page.evaluate(
            "() => typeof window.SentinelSDK !== 'undefined' && typeof window.SentinelSDK.token === 'function'"
        )
        if sentinel_ready:
            sentinel_token = await page.evaluate(
                """async (deviceId) => {
                    try {
                        return await window.SentinelSDK.token('sora_2_create_task__auto', deviceId);
                    } catch (error) {
                        return null;
                    }
                }""",
                page_context.device_id,
            )
        if not sentinel_token:
            raise BrowserAuthError(
                AUTH_ERROR_CODES["SENTINEL_NOT_READY"],
                "Sentinel SDK is not ready in page context",
            )

    return AuthContext(
        access_token=access_token,
        cookie_header=page_context.cookie_header,
        user_agent=page_context.user_agent,
        device_id=page_context.device_id,
        sentinel_token=sentinel_token,
        sentinel_ready=bool(sentinel_token) if require_sentinel else sentinel_ready,
        source="page_auth_session",
        refreshed_at=datetime.now(),
    )


async def refresh_auth_context(
    provider: BrowserProvider,
    db: Database,
    token: Token,
    handle: BrowserHandle,
    *,
    target_url: str,
    require_sentinel: bool,
) -> AuthContext:
    """Refresh auth context from the live page, with one reconnect/reopen recovery path."""
    try:
        auth_context = await _extract_auth_context(handle, provider, target_url, require_sentinel)
    except BrowserAuthError as exc:
        if exc.code in {
            AUTH_ERROR_CODES["TARGET_CLOSED"],
            AUTH_ERROR_CODES["EXECUTION_CONTEXT_DESTROYED"],
            AUTH_ERROR_CODES["SENTINEL_NOT_READY"],
        }:
            debug_logger.log_warning(f"[Auth] recover profile={token.browser_profile_id or token.id} code={exc.code}")
            recovered = await provider.recover_profile(
                token.browser_profile_id or str(token.id),
                token.browser_profile_path or "",
            )
            auth_context = await _extract_auth_context(recovered, provider, target_url, require_sentinel)
            handle.page = recovered.page
            handle.context = recovered.context
            handle.driver = recovered.driver
            handle.window_id = recovered.window_id
        else:
            raise

    await db.update_token_account_snapshot(
        token.id,
        account_state="ready",
        account_state_reason=None,
        source_of_truth="page_auth_session",
        last_auth_refresh_at=auth_context.refreshed_at,
        last_browser_check_at=auth_context.refreshed_at,
        last_auth_error_code=None,
    )
    return auth_context


@asynccontextmanager
async def browser_session(
    provider: BrowserProvider,
    db: Database,
    lock_manager: BrowserLockManager,
    token: Token,
    *,
    target_url: str,
    require_sentinel: bool = True,
    close_on_exit: bool = True,
) -> AsyncIterator[ManagedBrowserSession]:
    """Acquire profile/window locks and produce a fresh browser-backed auth context."""
    profile_id = token.browser_profile_id or str(token.id)
    if not token.browser_profile_path:
        raise BrowserAuthError(
            AUTH_ERROR_CODES["AUTH_CONTEXT_INVALID"],
            f"Token {token.id} is missing browser_profile_path",
        )

    async with lock_manager.profile_lock(profile_id):
        async with lock_manager.startup_lock():
            try:
                handle = await provider.connect_profile(profile_id, token.browser_profile_path)
            except BrowserAuthError:
                raise
            except Exception as exc:
                raise BrowserAuthError(AUTH_ERROR_CODES["ECONNREFUSED"], str(exc)) from exc

        async with lock_manager.window_lock(handle.window_id):
            readiness = await provider.readiness_check(handle, target_url)
            if readiness.challenge_detected:
                await db.update_token_account_snapshot(
                    token.id,
                    account_state="challenge",
                    account_state_reason="cloudflare_challenge",
                    source_of_truth="page_readiness_check",
                    last_browser_check_at=datetime.now(),
                    last_auth_error_code=AUTH_ERROR_CODES["CLOUDFLARE_CHALLENGE"],
                )
                raise BrowserAuthError(
                    AUTH_ERROR_CODES["CLOUDFLARE_CHALLENGE"],
                    readiness.message or "Cloudflare challenge detected",
                )

            auth_context = await refresh_auth_context(
                provider,
                db,
                token,
                handle,
                target_url=target_url,
                require_sentinel=require_sentinel,
            )
            session = ManagedBrowserSession(
                provider=provider,
                db=db,
                token=token,
                handle=handle,
                auth_context=auth_context,
                lock_manager=lock_manager,
                close_on_exit=close_on_exit,
            )
            try:
                yield session
            finally:
                await session.close()
