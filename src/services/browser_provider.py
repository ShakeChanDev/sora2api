"""Browser provider abstraction and NSTBrowser API/CDP-backed implementation."""
import json
import re
import sqlite3
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, Optional
from urllib.parse import urlparse
from uuid import uuid4

import jwt
from curl_cffi.requests import AsyncSession

from ..core.config import config
from ..core.logger import debug_logger
from .browser_runtime import AUTH_ERROR_CODES, BrowserAuthError, BrowserHandle, BrowserReadiness, PageContext

try:
    from playwright.async_api import TimeoutError as PlaywrightTimeoutError
    from playwright.async_api import async_playwright

    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    PlaywrightTimeoutError = TimeoutError


CHALLENGE_MARKERS = (
    "Just a moment",
    "Enable JavaScript and cookies to continue",
    "Verify you are human",
    "Checking your browser before accessing",
    "Attention Required!",
)

NST_AGENT_CONFIG_DB = Path.home() / ".nst-agent" / "config"
NST_LOCAL_STORAGE_DIR = Path.home() / "AppData" / "Roaming" / "nstbrowser" / "Local Storage" / "leveldb"
JWT_PATTERN = re.compile(r"eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+")


class BrowserProvider(ABC):
    """Abstract browser provider interface."""

    @abstractmethod
    async def start_profile(self, profile_id: str, profile_path: str) -> BrowserHandle:
        raise NotImplementedError

    @abstractmethod
    async def connect_profile(self, profile_id: str, profile_path: str) -> BrowserHandle:
        raise NotImplementedError

    @abstractmethod
    async def stop_profile(self, profile_id: str):
        raise NotImplementedError

    @abstractmethod
    async def recover_profile(self, profile_id: str, profile_path: str) -> BrowserHandle:
        raise NotImplementedError

    @abstractmethod
    async def readiness_check(self, handle: BrowserHandle, target_url: str) -> BrowserReadiness:
        raise NotImplementedError

    @abstractmethod
    async def get_page_context(self, handle: BrowserHandle, target_url: str) -> PageContext:
        raise NotImplementedError

    @abstractmethod
    async def execute_in_page(self, handle: BrowserHandle, action: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError


class NstBrowserProvider(BrowserProvider):
    """Provider backed by the local NSTBrowser API and CDP attach."""

    def __init__(self):
        self._handles: Dict[str, BrowserHandle] = {}
        self._agent_port: Optional[int] = None
        self._api_tokens: Optional[list[str]] = None

    def _resolve_profile_path(self, profile_id: str, profile_path: str) -> str:
        explicit = (profile_path or "").strip()
        if explicit:
            return explicit

        root = config.browser_profiles_root.strip()
        if root:
            return str(Path(root) / profile_id)

        return str(Path.home() / ".nst-agent" / "profiles" / profile_id)

    def _load_agent_port(self) -> int:
        if self._agent_port is not None:
            return self._agent_port

        if not NST_AGENT_CONFIG_DB.exists():
            self._agent_port = 8848
            return self._agent_port

        try:
            conn = sqlite3.connect(NST_AGENT_CONFIG_DB)
            try:
                row = conn.execute("SELECT value FROM config WHERE key = 'user_config' LIMIT 1").fetchone()
            finally:
                conn.close()
            if row and row[0]:
                payload = json.loads(row[0])
                self._agent_port = int(payload.get("serverPort", 8848))
            else:
                self._agent_port = 8848
        except Exception as exc:
            debug_logger.log_warning(f"[Browser] failed to read NST agent port: {exc}")
            self._agent_port = 8848

        return self._agent_port

    def _iter_local_api_tokens(self) -> Iterable[str]:
        if not NST_LOCAL_STORAGE_DIR.exists():
            return []

        tokens: Dict[str, int] = {}
        for path in sorted(NST_LOCAL_STORAGE_DIR.glob("*")):
            if not path.is_file():
                continue
            try:
                content = path.read_bytes().decode("latin1", "ignore")
            except Exception:
                continue
            for match in JWT_PATTERN.finditer(content):
                token = match.group(0)
                if token in tokens:
                    continue
                try:
                    payload = jwt.decode(token, options={"verify_signature": False})
                    exp = int(payload.get("exp", 0))
                except Exception:
                    continue
                tokens[token] = exp

        return [token for token, _ in sorted(tokens.items(), key=lambda item: item[1], reverse=True)]

    def _load_local_api_tokens(self) -> list[str]:
        if self._api_tokens is not None:
            return self._api_tokens

        tokens = list(self._iter_local_api_tokens())
        if not tokens:
            raise BrowserAuthError(
                AUTH_ERROR_CODES["AUTH_CONTEXT_INVALID"],
                "NSTBrowser local app token not found; cannot call local NSTBrowser API",
            )
        self._api_tokens = tokens
        return tokens

    async def _agent_request(self, method: str, path: str, **kwargs) -> Dict[str, Any]:
        url = f"http://127.0.0.1:{self._load_agent_port()}{path}"
        last_error: Optional[str] = None
        base_headers = dict(kwargs.pop("headers", {}) or {})
        async with AsyncSession(timeout=config.browser_action_timeout) as session:
            for token in self._load_local_api_tokens():
                headers = dict(base_headers)
                headers["Authorization"] = f"Bearer {token}"
                response = await session.request(method, url, headers=headers, **kwargs)
                if response.status_code in {401, 403}:
                    last_error = f"status={response.status_code}"
                    continue
                if response.status_code >= 400:
                    raise BrowserAuthError(
                        AUTH_ERROR_CODES["ECONNREFUSED"],
                        f"NSTBrowser API request failed: {response.status_code} {response.text[:200]}",
                        upstream_status=response.status_code,
                    )
                payload = response.json()
                if payload.get("err"):
                    raise BrowserAuthError(
                        AUTH_ERROR_CODES["ECONNREFUSED"],
                        payload.get("msg") or "NSTBrowser API returned err=true",
                        upstream_status=payload.get("code"),
                    )
                return payload.get("data") or {}

        raise BrowserAuthError(
            AUTH_ERROR_CODES["AUTH_CONTEXT_INVALID"],
            f"NSTBrowser local API authentication failed ({last_error or 'no usable token'})",
        )

    def _build_handle(
        self,
        profile_id: str,
        profile_path: str,
        *,
        browser: Any,
        page: Any,
        context: Any,
        driver: Any,
        window_id: Optional[str] = None,
    ) -> BrowserHandle:
        return BrowserHandle(
            provider="nstbrowser",
            profile_id=profile_id,
            profile_path=profile_path,
            window_id=window_id or str(uuid4()),
            connected_at=datetime.now(),
            state="connected",
            browser=browser,
            page=page,
            context=context,
            driver=driver,
        )

    @staticmethod
    def _is_page_usable(page: Any) -> bool:
        if not page:
            return False
        try:
            if page.is_closed():
                return False
        except Exception:
            return False
        current_url = (getattr(page, "url", "") or "").strip().lower()
        if not current_url:
            return False
        return current_url.startswith("http://") or current_url.startswith("https://")

    @classmethod
    def _page_matches_target(cls, page: Any, target_url: str) -> bool:
        if not cls._is_page_usable(page):
            return False
        page_url = urlparse((getattr(page, "url", "") or "").strip())
        target = urlparse((target_url or "").strip())
        if not page_url.hostname or not target.hostname:
            return False
        if page_url.hostname != target.hostname:
            return False
        return "/cdn-cgi/" not in page_url.path.lower()

    def _find_existing_page(self, context: Any, target_url: Optional[str] = None) -> Optional[Any]:
        pages = [page for page in getattr(context, "pages", []) if self._is_page_usable(page)]
        if not pages:
            return None

        if target_url:
            exact_target = target_url.rstrip("/")
            for page in pages:
                if (getattr(page, "url", "") or "").rstrip("/") == exact_target:
                    return page
            for page in pages:
                if self._page_matches_target(page, target_url):
                    return page

        return pages[0]

    async def _attach_cdp(self, profile_id: str, profile_path: str, debugger_info: Dict[str, Any]) -> BrowserHandle:
        if not PLAYWRIGHT_AVAILABLE:
            raise BrowserAuthError(
                AUTH_ERROR_CODES["AUTH_CONTEXT_INVALID"],
                "Playwright is not installed; browser-backed auth refresh is unavailable",
            )

        port = debugger_info.get("port")
        if not port:
            raise BrowserAuthError(
                AUTH_ERROR_CODES["ECONNREFUSED"],
                f"NSTBrowser debugger info missing port for profile {profile_id}",
            )

        driver = await async_playwright().start()
        browser = await driver.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
        context = browser.contexts[0] if browser.contexts else None
        if context is None:
            await driver.stop()
            raise BrowserAuthError(
                AUTH_ERROR_CODES["AUTH_CONTEXT_INVALID"],
                f"NSTBrowser profile {profile_id} did not expose a browser context over CDP",
            )
        page = self._find_existing_page(context, "https://sora.chatgpt.com/explore")
        if page is None:
            page = await context.new_page()
        handle = self._build_handle(
            profile_id,
            self._resolve_profile_path(profile_id, profile_path),
            browser=browser,
            page=page,
            context=context,
            driver=driver,
            window_id=str(port),
        )
        self._handles[profile_id] = handle
        debug_logger.log_info(f"[Browser] attached profile={profile_id} cdp_port={port}")
        return handle

    async def _fetch_debugger(self, profile_id: str) -> Dict[str, Any]:
        return await self._agent_request("GET", f"/api/v2/browsers/{profile_id}/debugger")

    async def _ensure_page(self, handle: BrowserHandle) -> BrowserHandle:
        if self._is_page_usable(handle.page):
            return handle
        if handle.context:
            existing = self._find_existing_page(handle.context)
            if existing is not None:
                handle.page = existing
                return handle
        if handle.context and handle.context.pages:
            handle.page = handle.context.pages[0]
            return handle
        handle.page = await handle.context.new_page()
        return handle

    async def _ensure_target_page(self, handle: BrowserHandle, target_url: str) -> BrowserHandle:
        handle = await self._ensure_page(handle)
        existing = self._find_existing_page(handle.context, target_url) if handle.context else None
        if existing is not None:
            handle.page = existing
        if self._page_matches_target(handle.page, target_url):
            return handle
        await handle.page.goto(target_url, wait_until="domcontentloaded", timeout=config.browser_startup_timeout * 1000)
        return handle

    async def start_profile(self, profile_id: str, profile_path: str) -> BrowserHandle:
        await self._agent_request("POST", f"/api/v2/browsers/{profile_id}")
        debugger_info = await self._fetch_debugger(profile_id)
        return await self._attach_cdp(profile_id, profile_path, debugger_info)

    async def connect_profile(self, profile_id: str, profile_path: str) -> BrowserHandle:
        existing = self._handles.get(profile_id)
        if existing and existing.context:
            return await self._ensure_page(existing)

        try:
            debugger_info = await self._fetch_debugger(profile_id)
        except BrowserAuthError:
            return await self.start_profile(profile_id, profile_path)
        return await self._attach_cdp(profile_id, profile_path, debugger_info)

    async def stop_profile(self, profile_id: str):
        handle = self._handles.pop(profile_id, None)
        if not handle:
            return

        try:
            await self._agent_request("DELETE", f"/api/v2/browsers/{profile_id}")
            debug_logger.log_info(f"[Browser] closed remote profile window={profile_id}")
        except Exception as exc:
            debug_logger.log_warning(f"[Browser] remote close failed profile={profile_id}: {exc}")

        try:
            if handle.page and not handle.page.is_closed():
                await handle.page.close()
        except Exception:
            pass
        try:
            if handle.driver:
                await handle.driver.stop()
        except Exception:
            pass
        debug_logger.log_info(f"[Browser] detached profile={profile_id}")

    async def recover_profile(self, profile_id: str, profile_path: str) -> BrowserHandle:
        await self.stop_profile(profile_id)
        return await self.connect_profile(profile_id, profile_path)

    async def readiness_check(self, handle: BrowserHandle, target_url: str) -> BrowserReadiness:
        handle = await self._ensure_target_page(handle, target_url)
        try:
            await handle.page.wait_for_timeout(1500)
            current_url = (handle.page.url or "").lower()
            title = (await handle.page.title() or "").strip()
            body_text = await handle.page.evaluate(
                "() => (document.body && document.body.innerText) ? document.body.innerText : ''"
            )
            combined_text = f"{title}\n{body_text}".lower()
            challenge_detected = "/cdn-cgi/" in current_url or any(
                marker.lower() in combined_text for marker in CHALLENGE_MARKERS
            )
            sentinel_ready = False
            try:
                sentinel_ready = await handle.page.evaluate(
                    "() => typeof window.SentinelSDK !== 'undefined' && typeof window.SentinelSDK.token === 'function'"
                )
            except Exception:
                sentinel_ready = False

            return BrowserReadiness(
                ready=not challenge_detected,
                page_url=handle.page.url,
                challenge_detected=challenge_detected,
                sentinel_ready=sentinel_ready,
                message="cloudflare challenge" if challenge_detected else None,
            )
        except PlaywrightTimeoutError as exc:
            raise BrowserAuthError(AUTH_ERROR_CODES["AUTH_CONTEXT_INVALID"], f"Page readiness timeout: {exc}") from exc
        except Exception as exc:
            lowered = str(exc).lower()
            if "target closed" in lowered:
                raise BrowserAuthError(AUTH_ERROR_CODES["TARGET_CLOSED"], str(exc)) from exc
            raise BrowserAuthError(AUTH_ERROR_CODES["AUTH_CONTEXT_INVALID"], str(exc)) from exc

    async def get_page_context(self, handle: BrowserHandle, target_url: str) -> PageContext:
        handle = await self._ensure_target_page(handle, target_url)
        user_agent = await handle.page.evaluate("() => navigator.userAgent")
        cookies = await handle.context.cookies(["https://sora.chatgpt.com", "https://chatgpt.com"])
        cookie_header = "; ".join(f"{item['name']}={item['value']}" for item in cookies)
        device_id = None
        for cookie in cookies:
            if cookie.get("name") == "oai-did":
                device_id = cookie.get("value")
                break
        return PageContext(
            page_url=handle.page.url,
            user_agent=user_agent,
            cookie_header=cookie_header,
            device_id=device_id,
            session_fetched_at=datetime.now(),
        )

    async def execute_in_page(self, handle: BrowserHandle, action: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        handle = await self._ensure_page(handle)
        action_timeout_ms = config.browser_action_timeout * 1000

        try:
            if action == "json_fetch":
                target_url = payload.get("target_url")
                if target_url:
                    handle = await self._ensure_target_page(handle, target_url)
                return await handle.page.evaluate(
                    """async (payload) => {
                        const doFetch = async (request) => {
                            const response = await fetch(request.url, {
                                method: request.method || 'GET',
                                headers: request.headers || {},
                                body: request.body ? JSON.stringify(request.body) : undefined,
                                credentials: 'include',
                            });
                            const text = await response.text();
                            let json = null;
                            try {
                                json = JSON.parse(text);
                            } catch (_) {}
                            return { ok: response.ok, status: response.status, text, json, url: response.url };
                        };

                        const warmupResults = [];
                        for (const request of (payload.warmup_requests || [])) {
                            try {
                                if (request.kind === 'refresh_sentinel') {
                                    if (typeof window.SentinelSDK !== 'undefined' && typeof window.SentinelSDK.token === 'function') {
                                        const token = await window.SentinelSDK.token(
                                            request.action || 'sora_2_create_task__auto',
                                            request.device_id || null,
                                        );
                                        warmupResults.push({ ok: !!token, kind: request.kind });
                                        if (token && request.apply_to_request && payload.headers) {
                                            payload.headers['openai-sentinel-token'] = token;
                                        }
                                    } else {
                                        warmupResults.push({ ok: false, kind: request.kind });
                                    }
                                    continue;
                                }
                                const result = await doFetch(request);
                                warmupResults.push({
                                    ok: result.ok,
                                    status: result.status,
                                    kind: request.kind || 'fetch',
                                    url: result.url,
                                });
                                if (!result.ok && !request.ignore_failure) {
                                    result.warmup_results = warmupResults;
                                    return result;
                                }
                            } catch (error) {
                                warmupResults.push({
                                    ok: false,
                                    kind: request.kind || 'fetch',
                                    error: String(error),
                                });
                                if (!request.ignore_failure) {
                                    return {
                                        ok: false,
                                        status: 0,
                                        text: String(error),
                                        json: null,
                                        url: request.url || '',
                                        warmup_results: warmupResults,
                                    };
                                }
                            }
                        }

                        const result = await doFetch(payload);
                        result.warmup_results = warmupResults;
                        return result;
                    }""",
                    payload,
                )

            if action == "ui_video_submit":
                target_url = payload.get("target_url")
                if target_url:
                    handle = await self._ensure_target_page(handle, target_url)

                prompt = (payload.get("prompt") or "").strip()
                if not prompt:
                    raise BrowserAuthError(
                        AUTH_ERROR_CODES["AUTH_CONTEXT_INVALID"],
                        "ui_video_submit requires a non-empty prompt",
                    )

                prompt_input = handle.page.get_by_placeholder("Describe your video...")
                await prompt_input.wait_for(timeout=action_timeout_ms)
                await prompt_input.fill(prompt, timeout=action_timeout_ms)
                await handle.page.wait_for_timeout(500)

                response_future = handle.page.wait_for_response(
                    lambda resp: "/backend/nf/create" in resp.url and resp.request.method == "POST",
                    timeout=action_timeout_ms,
                )
                button = handle.page.get_by_role("button", name="Create video")
                await button.click(timeout=action_timeout_ms)
                response = await response_future
                text = await response.text()
                try:
                    json_payload = json.loads(text)
                except Exception:
                    json_payload = None
                return {"ok": response.ok, "status": response.status, "text": text, "json": json_payload, "url": response.url}

            if action == "publish_click":
                draft_url = payload["draft_url"]
                await handle.page.goto(draft_url, wait_until="domcontentloaded", timeout=action_timeout_ms)
                response_future = handle.page.wait_for_response(
                    lambda resp: "/backend/project_y/post" in resp.url and resp.request.method == "POST",
                    timeout=action_timeout_ms,
                )
                button = handle.page.get_by_role("button", name="Post")
                await button.click(timeout=action_timeout_ms)
                response = await response_future
                text = await response.text()
                try:
                    json_payload = await response.json()
                except Exception:
                    json_payload = None
                return {"ok": response.ok, "status": response.status, "text": text, "json": json_payload, "url": response.url}

            raise BrowserAuthError(
                AUTH_ERROR_CODES["AUTH_CONTEXT_INVALID"],
                f"Unsupported in-page action: {action}",
            )
        except PlaywrightTimeoutError as exc:
            raise BrowserAuthError(AUTH_ERROR_CODES["EXECUTION_CONTEXT_DESTROYED"], str(exc)) from exc
        except BrowserAuthError:
            raise
        except Exception as exc:
            lowered = str(exc).lower()
            if "target closed" in lowered:
                raise BrowserAuthError(AUTH_ERROR_CODES["TARGET_CLOSED"], str(exc)) from exc
            if "execution context was destroyed" in lowered:
                raise BrowserAuthError(AUTH_ERROR_CODES["EXECUTION_CONTEXT_DESTROYED"], str(exc)) from exc
            raise
