import asyncio
import unittest
from datetime import datetime

from src.services.browser_provider import NstBrowserProvider
from src.services.browser_runtime import BrowserHandle


class _FakeLocator:
    def __init__(self, page, kind: str):
        self.page = page
        self.kind = kind

    async def wait_for(self, timeout=None):
        return None

    async def fill(self, value, timeout=None):
        self.page.filled_prompt = value

    async def click(self, timeout=None):
        self.page.clicked = True


class _FakeResponse:
    def __init__(self, *, url: str, status: int = 200, text: str = "{\"id\":\"ui-task\"}"):
        self.url = url
        self.status = status
        self.ok = status < 400
        self._text = text
        self.request = type("Req", (), {"method": "POST"})()

    async def text(self):
        return self._text


class _FakePage:
    def __init__(self, url: str, *, content: str = "<html></html>"):
        self.url = url
        self._content = content
        self.goto_calls = 0
        self.closed = False
        self.filled_prompt = None
        self.clicked = False

    def is_closed(self):
        return self.closed

    async def goto(self, url, wait_until=None, timeout=None):
        self.goto_calls += 1
        self.url = url

    async def wait_for_timeout(self, ms):
        return None

    async def content(self):
        return self._content

    async def evaluate(self, script, payload=None):
        if script.strip() == "() => typeof window.SentinelSDK !== 'undefined' && typeof window.SentinelSDK.token === 'function'":
            return True
        return {"ok": True, "status": 200, "json": {"id": "page-task"}, "text": "{\"id\":\"page-task\"}", "url": payload["url"]}

    def get_by_placeholder(self, name):
        return _FakeLocator(self, "placeholder")

    def get_by_role(self, role, name=None):
        return _FakeLocator(self, f"{role}:{name}")

    def wait_for_response(self, predicate, timeout=None):
        return asyncio.create_task(
            asyncio.sleep(
                0,
                result=_FakeResponse(url="https://sora.chatgpt.com/backend/nf/create"),
            )
        )

    async def close(self):
        self.closed = True


class _FakeContext:
    def __init__(self, pages):
        self.pages = pages

    async def new_page(self):
        page = _FakePage("https://sora.chatgpt.com/explore")
        self.pages.append(page)
        return page

    async def cookies(self, urls):
        return [
            {"name": "oai-did", "value": "device-1"},
            {"name": "session", "value": "cookie-1"},
        ]


class BrowserProviderTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.provider = NstBrowserProvider()

    def _make_handle(self, page, *other_pages):
        context = _FakeContext([page, *other_pages])
        return BrowserHandle(
            provider="nstbrowser",
            profile_id="profile-1",
            profile_path="C:/profiles/profile-1",
            window_id="window-1",
            connected_at=datetime.now(),
            state="connected",
            page=page,
            context=context,
            driver=object(),
        )

    async def test_ensure_target_page_reuses_existing_sora_tab_without_navigation(self):
        current_page = _FakePage("https://sora.chatgpt.com/c/library")
        handle = self._make_handle(current_page)

        await self.provider._ensure_target_page(handle, "https://sora.chatgpt.com/explore")

        self.assertIs(handle.page, current_page)
        self.assertEqual(current_page.goto_calls, 0)

    async def test_ensure_target_page_switches_to_existing_sora_tab_before_navigation(self):
        wrong_page = _FakePage("https://example.com")
        sora_page = _FakePage("https://sora.chatgpt.com/explore")
        handle = self._make_handle(wrong_page, sora_page)

        await self.provider._ensure_target_page(handle, "https://sora.chatgpt.com/explore")

        self.assertIs(handle.page, sora_page)
        self.assertEqual(wrong_page.goto_calls, 0)
        self.assertEqual(sora_page.goto_calls, 0)

    async def test_json_fetch_uses_warm_page_without_extra_navigation(self):
        page = _FakePage("https://sora.chatgpt.com/explore")
        handle = self._make_handle(page)

        response = await self.provider.execute_in_page(
            handle,
            "json_fetch",
            {
                "target_url": "https://sora.chatgpt.com/explore",
                "url": "https://sora.chatgpt.com/backend/nf/create",
                "method": "POST",
                "headers": {"Authorization": "Bearer page-at"},
                "body": {"prompt": "test"},
            },
        )

        self.assertEqual(page.goto_calls, 0)
        self.assertTrue(response["ok"])
        self.assertEqual(response["json"]["id"], "page-task")

    async def test_ui_video_submit_clicks_existing_warm_page(self):
        page = _FakePage("https://sora.chatgpt.com/explore")
        handle = self._make_handle(page)

        response = await self.provider.execute_in_page(
            handle,
            "ui_video_submit",
            {
                "target_url": "https://sora.chatgpt.com/explore",
                "prompt": "native submit prompt",
            },
        )

        self.assertEqual(page.goto_calls, 0)
        self.assertEqual(page.filled_prompt, "native submit prompt")
        self.assertTrue(page.clicked)
        self.assertTrue(response["ok"])
        self.assertEqual(response["json"]["id"], "ui-task")


if __name__ == "__main__":
    unittest.main()
