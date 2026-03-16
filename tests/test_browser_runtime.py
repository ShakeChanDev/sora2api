import asyncio
import unittest

from src.services.browser_runtime import (
    BrowserLockManager,
    classify_high_risk_failure,
    extract_upstream_error,
)


class BrowserLockManagerTests(unittest.IsolatedAsyncioTestCase):
    async def test_profile_lock_serializes_same_profile(self):
        manager = BrowserLockManager()
        events = []
        first_entered = asyncio.Event()

        async def first():
            async with manager.profile_lock("profile-1"):
                events.append("first-start")
                first_entered.set()
                await asyncio.sleep(0.05)
                events.append("first-end")

        async def second():
            await first_entered.wait()
            async with manager.profile_lock("profile-1"):
                events.append("second-start")
                events.append("second-end")

        await asyncio.gather(first(), second())
        self.assertEqual(
            events,
            ["first-start", "first-end", "second-start", "second-end"],
        )


class BrowserFailureClassificationTests(unittest.TestCase):
    def test_timeout_like_error_is_high_risk(self):
        self.assertTrue(
            classify_high_risk_failure(
                RuntimeError("curl: (28) Operation timed out after 45014 milliseconds with 0 bytes received")
            )
        )

    def test_invalid_request_is_high_risk_for_page_fallback(self):
        error = extract_upstream_error(
            {
                "status": 400,
                "json": {
                    "error": {
                        "message": "Unable to process request",
                        "code": "invalid_request",
                    }
                },
            },
            "video submit failed",
        )
        self.assertTrue(error.high_risk)
        self.assertTrue(classify_high_risk_failure(error))


if __name__ == "__main__":
    unittest.main()
