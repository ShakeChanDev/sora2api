import argparse
import asyncio
import json
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

from playwright.async_api import async_playwright

from src.services.browser_runtime import AuthContext, UpstreamExecutionError
from src.services.sora_client import SoraClient


class NoProxyManager:
    async def get_proxy_url(self, *args, **kwargs):
        return None


async def wait_for_sentinel(page, timeout_s: int = 30) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        ready = await page.evaluate(
            "() => typeof window.SentinelSDK !== 'undefined' && typeof window.SentinelSDK.token === 'function'"
        )
        if ready:
            return
        await page.wait_for_timeout(500)
    raise RuntimeError("sentinel_not_ready")


async def extract_auth_context(page, context) -> AuthContext:
    await page.goto("https://sora.chatgpt.com/explore", wait_until="domcontentloaded", timeout=120000)
    await wait_for_sentinel(page)

    session = await page.evaluate(
        """async () => {
            const response = await fetch('/api/auth/session', { credentials: 'include' });
            const text = await response.text();
            let json = null;
            try { json = JSON.parse(text); } catch (_) {}
            return { ok: response.ok, status: response.status, text, json };
        }"""
    )
    if not session.get("ok") or not session.get("json") or not session["json"].get("accessToken"):
        raise RuntimeError(f"auth_context_invalid status={session.get('status')}")

    user_agent = await page.evaluate("() => navigator.userAgent")
    cookies = await context.cookies(["https://sora.chatgpt.com", "https://chatgpt.com"])
    cookie_header = "; ".join(f"{item['name']}={item['value']}" for item in cookies)
    device_id = None
    for cookie in cookies:
        if cookie.get("name") == "oai-did":
            device_id = cookie.get("value")
            break

    sentinel_token = await page.evaluate(
        """async (deviceId) => {
            return await window.SentinelSDK.token('sora_2_create_task__auto', deviceId);
        }""",
        device_id,
    )
    if not sentinel_token:
        raise RuntimeError("sentinel_not_ready")

    return AuthContext(
        access_token=session["json"]["accessToken"],
        cookie_header=cookie_header,
        user_agent=user_agent,
        device_id=device_id,
        sentinel_token=sentinel_token,
        sentinel_ready=True,
        source="nstbrowser_cdp",
        refreshed_at=datetime.now(),
    )


async def submit_via_page(page, auth_context: AuthContext, payload: dict) -> dict:
    response = await page.evaluate(
        """async ({payload, accessToken, deviceId, sentinelToken}) => {
            const response = await fetch('/backend/nf/create', {
                method: 'POST',
                credentials: 'include',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${accessToken}`,
                    'oai-device-id': deviceId || '',
                    'openai-sentinel-token': sentinelToken || '',
                },
                body: JSON.stringify(payload),
            });
            const text = await response.text();
            let json = null;
            try { json = JSON.parse(text); } catch (_) {}
            return { ok: response.ok, status: response.status, text, json, url: response.url };
        }""",
        {
            "payload": payload,
            "accessToken": auth_context.access_token,
            "deviceId": auth_context.device_id,
            "sentinelToken": auth_context.sentinel_token,
        },
    )
    if not response.get("ok"):
        raise UpstreamExecutionError(
            f"Page submit failed status={response.get('status')}",
            status_code=response.get("status"),
            response_body=response.get("json") or response.get("text"),
            high_risk=response.get("status") in {401, 403},
        )
    if not response.get("json") or not response["json"].get("id"):
        raise RuntimeError(f"page_submit_invalid_response: {response.get('text')}")
    return response["json"]


async def poll_until_complete(
    client: SoraClient,
    page,
    context,
    task_id: str,
    *,
    auth_context: AuthContext,
    poll_interval: int,
    timeout_s: int,
) -> dict:
    started = time.time()
    last_progress: Optional[int] = None

    while time.time() - started < timeout_s:
        try:
            pending_tasks = await client.get_pending_tasks(auth_context.access_token)
        except Exception as exc:
            if "401" in str(exc) or "403" in str(exc):
                print("poll auth expired, refreshing auth context")
                auth_context = await extract_auth_context(page, context)
                pending_tasks = await client.get_pending_tasks(auth_context.access_token)
            else:
                raise

        task_found = False
        for task in pending_tasks:
            if task.get("id") == task_id:
                task_found = True
                progress_pct = task.get("progress_pct")
                progress = 0 if progress_pct is None else int(progress_pct * 100)
                if progress != last_progress:
                    print(f"progress={progress}% status={task.get('status')}")
                    last_progress = progress
                break

        if not task_found:
            drafts = await client.get_video_drafts(auth_context.access_token, limit=50)
            for item in drafts.get("items", []):
                if item.get("task_id") != task_id:
                    continue
                reason = item.get("reason_str") or item.get("markdown_reason_str")
                url = item.get("downloadable_url") or item.get("url")
                kind = item.get("kind")
                if kind == "sora_content_violation" or reason or not url:
                    raise RuntimeError(
                        f"generation_failed kind={kind} reason={reason or '-'} has_url={bool(url)}"
                    )
                return {
                    "task_id": task_id,
                    "generation_id": item.get("id"),
                    "url": url,
                    "draft_kind": kind,
                }

        await asyncio.sleep(poll_interval)

    raise TimeoutError(f"generation timed out after {timeout_s}s")


async def run(args):
    client = SoraClient(NoProxyManager())
    async with async_playwright() as playwright:
        browser = await playwright.chromium.connect_over_cdp(args.cdp_url)
        if not browser.contexts:
            raise RuntimeError("No browser contexts available via CDP")
        context = browser.contexts[0]
        page = await context.new_page()
        try:
            auth_context = await extract_auth_context(page, context)
            payload = client._build_video_payload(
                args.prompt,
                orientation=args.orientation,
                size=args.size,
                n_frames=args.n_frames,
                model=args.sora_model,
                inpaint_items=[],
                style_id=None,
            )

            submit_mode = "replay_http"
            try:
                print("submit strategy=replay_http")
                submit_result = await client.generate_video(
                    args.prompt,
                    auth_context.access_token,
                    orientation=args.orientation,
                    n_frames=args.n_frames,
                    model=args.sora_model,
                    size=args.size,
                    auth_context=auth_context,
                )
                task_id = submit_result
            except Exception as exc:
                print(f"replay submit failed: {exc}")
                submit_mode = "page_execute"
                auth_context = await extract_auth_context(page, context)
                print("submit strategy=page_execute")
                response = await submit_via_page(page, auth_context, payload)
                task_id = response["id"]

            print(f"task_id={task_id}")
            result = await poll_until_complete(
                client,
                page,
                context,
                task_id,
                auth_context=auth_context,
                poll_interval=args.poll_interval,
                timeout_s=args.timeout,
            )
            output = {
                "ok": True,
                "submit_mode": submit_mode,
                "task_id": result["task_id"],
                "generation_id": result["generation_id"],
                "url": result["url"],
            }
            print(json.dumps(output, ensure_ascii=False))

            if args.output_json:
                Path(args.output_json).write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
        finally:
            await page.close()


def parse_args():
    parser = argparse.ArgumentParser(description="Real NSTBrowser video self-test")
    parser.add_argument("--cdp-url", default="http://127.0.0.1:58759")
    parser.add_argument("--prompt")
    parser.add_argument("--prompt-file")
    parser.add_argument("--orientation", default="landscape")
    parser.add_argument("--n-frames", type=int, default=300)
    parser.add_argument("--sora-model", default="sy_8")
    parser.add_argument("--size", default="small")
    parser.add_argument("--poll-interval", type=int, default=15)
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("--output-json")
    args = parser.parse_args()
    if args.prompt_file:
        args.prompt = Path(args.prompt_file).read_text(encoding="utf-8").strip()
    if not args.prompt:
        parser.error("one of --prompt or --prompt-file is required")
    return args


if __name__ == "__main__":
    asyncio.run(run(parse_args()))
