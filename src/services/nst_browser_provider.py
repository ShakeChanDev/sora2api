"""NSTBrowser-backed page execution provider."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, Optional

from curl_cffi.requests import AsyncSession
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import async_playwright

from ..core.config import config
from ..core.logger import debug_logger
from .browser_provider import (
    AuthContext,
    BrowserAuthError,
    BrowserConnection,
    BrowserMutationError,
    BrowserMutationRequest,
    BrowserMutationResponse,
    BrowserPageContext,
    BrowserProvider,
    BrowserProviderError,
    BrowserReadinessError,
    EgressBinding,
    EgressProbeObservation,
)


class NSTBrowserProvider(BrowserProvider):
    """Browser provider implementation for NSTBrowser local API."""

    provider_name = "nst"

    def __init__(self, base_url: Optional[str] = None, api_key: Optional[str] = None):
        self.base_url = (base_url or config.nst_browser_base_url).rstrip("/")
        self.api_key = api_key or config.nst_browser_api_key
        self.page_timeout_ms = config.browser_page_timeout_ms
        self.readiness_timeout_ms = config.browser_readiness_timeout_ms

    @property
    def _headers(self) -> Dict[str, str]:
        headers: Dict[str, str] = {}
        if self.api_key:
            headers["x-api-key"] = self.api_key
        return headers

    async def _request(self, method: str, path: str, json_data: Optional[dict] = None) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        async with AsyncSession(impersonate="chrome") as session:
            response = await session.request(
                method=method,
                url=url,
                headers=self._headers,
                json=json_data,
                timeout=30,
            )
        if response.status_code >= 400:
            raise BrowserProviderError("browser_provider_http_error", f"{method} {path} -> {response.status_code}: {response.text}")
        payload = response.json()
        if payload.get("err"):
            raise BrowserProviderError("browser_provider_api_error", payload.get("msg") or f"{method} {path} failed")
        return payload.get("data") or {}

    async def _request_debugger(self, profile_id: str) -> Optional[Dict[str, Any]]:
        try:
            debugger = await self._request("GET", f"/browsers/{profile_id}/debugger")
        except BrowserProviderError:
            return None
        return debugger if debugger.get("webSocketDebuggerUrl") else None

    async def start(self, profile_id: str) -> Dict[str, Any]:
        debugger = await self._request_debugger(profile_id)
        if debugger:
            return debugger

        last_error: Optional[BrowserProviderError] = None
        for path in (f"/browsers/{profile_id}", f"/browsers/{profile_id}/start"):
            try:
                result = await self._request("POST", path)
                if result.get("webSocketDebuggerUrl"):
                    return result
                debugger = await self._request_debugger(profile_id)
                if debugger:
                    return debugger
                return result
            except BrowserProviderError as exc:
                last_error = exc

        debugger = await self._request_debugger(profile_id)
        if debugger:
            return debugger
        if last_error:
            raise last_error
        raise BrowserProviderError("browser_provider_http_error", f"Failed to start NSTBrowser profile {profile_id}")

    async def stop(self, profile_id: str) -> Dict[str, Any]:
        return await self._request("POST", f"/browsers/{profile_id}/stop")

    async def _resolve_debugger(self, profile_id: str) -> Dict[str, Any]:
        debugger = await self._request_debugger(profile_id)
        if debugger:
            return debugger
        await self.start(profile_id)
        debugger = await self._request_debugger(profile_id)
        if debugger:
            return debugger
        raise BrowserProviderError("browser_debugger_missing", f"NSTBrowser profile {profile_id} has no debugger endpoint")

    async def _resolve_page(self, connection: BrowserConnection, preferred_url: Optional[str]) -> BrowserConnection:
        page = None
        page_id = None
        pages_payload = []
        try:
            pages_payload = await self._request("GET", f"/browsers/{connection.profile_id}/pages")
        except BrowserProviderError:
            pages_payload = []

        contexts = connection.browser.contexts
        if not contexts:
            raise BrowserReadinessError("browser_context_missing", "No browser context available for connected profile")
        context = contexts[0]

        if preferred_url:
            for api_page in pages_payload:
                if api_page.get("type") == "page" and api_page.get("url", "").startswith(preferred_url):
                    page_id = api_page.get("id")
                    for candidate in context.pages:
                        if candidate.url == api_page.get("url"):
                            page = candidate
                            break
                    if page:
                        break

        if page is None:
            for api_page in pages_payload:
                if api_page.get("type") == "page" and "sora.chatgpt.com" in api_page.get("url", ""):
                    page_id = api_page.get("id")
                    for candidate in context.pages:
                        if candidate.url == api_page.get("url"):
                            page = candidate
                            break
                    if page:
                        break

        if page is None:
            for candidate in context.pages:
                if "sora.chatgpt.com" in candidate.url:
                    page = candidate
                    break

        if page is None:
            page = await context.new_page()
            if preferred_url:
                await page.goto(preferred_url, wait_until="domcontentloaded", timeout=self.page_timeout_ms)

        connection.context = context
        connection.page = page
        connection.page_id = page_id
        return connection

    async def connect_profile(self, profile_id: str, preferred_url: Optional[str] = None) -> BrowserConnection:
        debugger = await self._resolve_debugger(profile_id)
        debugger_url = debugger.get("webSocketDebuggerUrl")
        if not debugger_url:
            raise BrowserProviderError("browser_debugger_missing", f"NSTBrowser profile {profile_id} has no debugger endpoint")

        playwright = await async_playwright().start()
        browser = await playwright.chromium.connect_over_cdp(debugger_url, timeout=self.page_timeout_ms)
        connection = BrowserConnection(
            provider=self.provider_name,
            profile_id=profile_id,
            debugger_url=debugger_url,
            proxy_url=debugger.get("proxy"),
            browser=browser,
            context=None,
            page=None,
            page_id=None,
            playwright=playwright,
        )
        return await self._resolve_page(connection, preferred_url)

    async def _detect_challenge(self, connection: BrowserConnection) -> Optional[str]:
        title = await connection.page.title()
        body_text = await connection.page.evaluate(
            """() => {
                const body = document.body ? document.body.innerText : '';
                return body ? body.slice(0, 4000) : '';
            }"""
        )
        haystack = f"{title}\n{body_text}".lower()
        if "just a moment" in haystack or "verify you are human" in haystack or "cloudflare" in haystack:
            return title or "cloudflare challenge"
        return None

    async def readiness_check(self, connection: BrowserConnection, preferred_url: Optional[str] = None) -> BrowserPageContext:
        page = connection.page
        target_url = preferred_url or "https://sora.chatgpt.com/explore"
        if not page.url.startswith("https://sora.chatgpt.com"):
            await page.goto(target_url, wait_until="domcontentloaded", timeout=self.page_timeout_ms)
        elif preferred_url and not page.url.startswith(preferred_url):
            await page.goto(target_url, wait_until="domcontentloaded", timeout=self.page_timeout_ms)

        await page.wait_for_load_state("domcontentloaded", timeout=self.readiness_timeout_ms)
        await page.wait_for_function(
            "() => document.readyState === 'interactive' || document.readyState === 'complete'",
            timeout=self.readiness_timeout_ms,
        )

        challenge = await self._detect_challenge(connection)
        if challenge:
            raise BrowserReadinessError("cloudflare_challenge", challenge)

        try:
            title = await page.title()
        except PlaywrightError as exc:
            raise BrowserReadinessError("TARGET_CLOSED", str(exc)) from exc

        return BrowserPageContext(
            profile_id=connection.profile_id,
            page_id=connection.page_id,
            page_url=page.url,
            title=title,
            provider=self.provider_name,
        )

    async def get_page_context(self, connection: BrowserConnection) -> BrowserPageContext:
        return BrowserPageContext(
            profile_id=connection.profile_id,
            page_id=connection.page_id,
            page_url=connection.page.url,
            title=await connection.page.title(),
            provider=self.provider_name,
        )

    async def _build_cookie_header(self, connection: BrowserConnection) -> str:
        cookies = await connection.context.cookies(["https://sora.chatgpt.com", "https://chatgpt.com"])
        ordered = []
        for cookie in cookies:
            name = cookie.get("name")
            value = cookie.get("value")
            if name and value:
                ordered.append(f"{name}={value}")
        return "; ".join(ordered)

    async def _probe_page_egress(self, page) -> Optional[EgressProbeObservation]:
        if not config.egress_probe_url:
            return None
        script = """
        async (probeUrl) => {
            const response = await fetch(probeUrl, {
                method: 'GET',
                credentials: 'omit',
                cache: 'no-store',
                headers: { 'Accept': 'application/json', 'Cache-Control': 'no-store' },
            });
            const text = await response.text();
            let payload = null;
            try {
                payload = JSON.parse(text);
            } catch (error) {
                payload = null;
            }
            return { status: response.status, payload, text };
        }
        """
        try:
            result = await page.evaluate(script, config.egress_probe_url)
        except PlaywrightError as exc:
            debug_logger.log_warning(f"[NSTBrowser] Page egress probe failed: {exc}")
            return None
        if result.get("status") != 200 or not isinstance(result.get("payload"), dict):
            debug_logger.log_warning(f"[NSTBrowser] Page egress probe returned {result.get('status')}")
            return None
        return EgressProbeObservation.from_payload(result.get("payload"))

    async def refresh_auth_context(
        self,
        connection: BrowserConnection,
        flow: str,
        preferred_url: Optional[str] = None,
    ) -> AuthContext:
        await self.readiness_check(connection, preferred_url=preferred_url)

        page = connection.page
        script = """
        async (flow) => {
            const ensureSdk = async () => {
                if (typeof window.SentinelSDK !== 'undefined' && typeof window.SentinelSDK.token === 'function') {
                    return;
                }
                await new Promise((resolve, reject) => {
                    const existing = document.querySelector('script[data-codex-sentinel-sdk="1"]');
                    if (existing) {
                        existing.addEventListener('load', () => resolve(), { once: true });
                        existing.addEventListener('error', () => reject(new Error('sdk_load_failed')), { once: true });
                        return;
                    }
                    const script = document.createElement('script');
                    script.src = 'https://chatgpt.com/backend-api/sentinel/sdk.js';
                    script.dataset.codexSentinelSdk = '1';
                    script.onload = () => resolve();
                    script.onerror = () => reject(new Error('sdk_load_failed'));
                    document.head.appendChild(script);
                });
            };

            const parseCookie = (name) => {
                const match = document.cookie
                    .split('; ')
                    .find((entry) => entry.startsWith(name + '='));
                return match ? match.split('=').slice(1).join('=') : null;
            };

            const response = await fetch('/api/auth/session', { credentials: 'include' });
            const text = await response.text();
            let payload = null;
            try {
                payload = JSON.parse(text);
            } catch (error) {
                payload = null;
            }

            await ensureSdk();
            const deviceId = parseCookie('oai-did');
            if (!deviceId) {
                throw new Error('device_id_missing');
            }
            if (typeof window.SentinelSDK === 'undefined' || typeof window.SentinelSDK.token !== 'function') {
                throw new Error('sentinel_not_ready');
            }

            const sentinelToken = await window.SentinelSDK.token(flow, deviceId);

            return {
                status: response.status,
                payload,
                text,
                deviceId,
                userAgent: navigator.userAgent,
                pageUrl: location.href,
                sentinelToken,
            };
        }
        """

        try:
            result = await page.evaluate(script, flow)
        except PlaywrightError as exc:
            message = str(exc)
            code = "execution_context_destroyed" if "Execution context was destroyed" in message else "TARGET_CLOSED"
            raise BrowserAuthError(code, message) from exc
        except Exception as exc:
            message = str(exc)
            code = "sentinel_not_ready" if "sentinel_not_ready" in message or "device_id_missing" in message else "auth_context_invalid"
            raise BrowserAuthError(code, message) from exc

        if result.get("status") != 200 or not isinstance(result.get("payload"), dict):
            raise BrowserAuthError("auth_context_invalid", f"/api/auth/session returned {result.get('status')}")

        access_token = result["payload"].get("accessToken")
        if not access_token:
            raise BrowserAuthError("auth_context_incomplete", "Missing accessToken in /api/auth/session response")

        sentinel_token = result.get("sentinelToken")
        if not sentinel_token:
            raise BrowserAuthError("sentinel_not_ready", "Missing sentinel token from page context")

        cookie_header = await self._build_cookie_header(connection)
        if not cookie_header:
            raise BrowserAuthError("auth_context_incomplete", "Missing cookie header from page context")

        expires_at = None
        expires = result["payload"].get("expires")
        if expires:
            try:
                expires_at = datetime.fromisoformat(expires.replace("Z", "+00:00"))
            except ValueError:
                expires_at = None

        device_id = result.get("deviceId")
        if not device_id:
            for cookie in await connection.context.cookies(["https://sora.chatgpt.com", "https://chatgpt.com"]):
                if cookie.get("name") == "oai-did":
                    device_id = cookie.get("value")
                    break

        browser_probe = await self._probe_page_egress(page)

        egress_binding = EgressBinding(
            provider=self.provider_name,
            profile_id=connection.profile_id,
            proxy_url=connection.proxy_url,
            page_url=result.get("pageUrl") or connection.page.url,
            browser_observation=browser_probe,
            same_network_identity_proven=False,
        )

        return AuthContext(
            access_token=access_token,
            cookie_header=cookie_header,
            user_agent=result.get("userAgent") or "",
            device_id=device_id,
            sentinel_token=sentinel_token,
            refreshed_at=datetime.utcnow(),
            provider=self.provider_name,
            profile_id=connection.profile_id,
            page_url=result.get("pageUrl") or connection.page.url,
            egress_binding=egress_binding,
            expires_at=expires_at,
            session_payload=result["payload"],
        )

    async def fetch_json(
        self,
        connection: BrowserConnection,
        request: BrowserMutationRequest,
        auth_context: AuthContext,
    ) -> BrowserMutationResponse:
        headers = dict(request.headers)
        headers.setdefault("Authorization", f"Bearer {auth_context.access_token}")
        headers.setdefault("openai-sentinel-token", auth_context.sentinel_token)
        if auth_context.device_id:
            headers.setdefault("oai-device-id", auth_context.device_id)
        if request.json_body is not None:
            headers.setdefault("Content-Type", "application/json")

        script = """
        async (args) => {
            const response = await fetch(args.url, {
                method: args.method,
                headers: args.headers,
                credentials: 'include',
                body: args.body,
            });
            const text = await response.text();
            let data = null;
            try {
                data = JSON.parse(text);
            } catch (error) {
                data = null;
            }
            return {
                status: response.status,
                ok: response.ok,
                headers: Object.fromEntries(response.headers.entries()),
                text,
                data,
                pageUrl: location.href,
            };
        }
        """
        payload = {
            "url": request.url,
            "method": request.method,
            "headers": headers,
            "body": json.dumps(request.json_body) if request.json_body is not None else None,
        }

        try:
            result = await connection.page.evaluate(script, payload)
        except PlaywrightError as exc:
            message = str(exc)
            code = "execution_context_destroyed" if "Execution context was destroyed" in message else "TARGET_CLOSED"
            raise BrowserMutationError(code, message) from exc

        response = BrowserMutationResponse(
            status=result["status"],
            ok=result["ok"],
            headers=result["headers"],
            data=result.get("data"),
            text=result.get("text") or "",
            page_url=result.get("pageUrl") or connection.page.url,
        )

        if request.expected_status is not None and response.status != request.expected_status:
            error_code = "cloudflare_challenge" if response.status in {403, 429} else "page_execute_failed"
            raise BrowserMutationError(error_code, f"{request.method} {request.url} -> {response.status}: {response.text[:1000]}")

        return response

    async def execute_in_page(self, connection: BrowserConnection, script: str, arg: Optional[dict] = None) -> Any:
        try:
            return await connection.page.evaluate(script, arg)
        except PlaywrightError as exc:
            message = str(exc)
            code = "execution_context_destroyed" if "Execution context was destroyed" in message else "TARGET_CLOSED"
            raise BrowserProviderError(code, message) from exc

    async def recover_same_profile(self, profile_id: str, preferred_url: Optional[str] = None) -> BrowserConnection:
        return await self.connect_profile(profile_id, preferred_url=preferred_url)

    async def disconnect(self, connection: BrowserConnection):
        if connection.playwright:
            await connection.playwright.stop()
