"""Tests for browser runtime delayed stop coordination."""
import asyncio
import unittest

from src.services.browser_runtime import BrowserRuntime


class BrowserRuntimeTests(unittest.TestCase):
    def test_profile_lock_cancels_pending_delayed_stop(self):
        async def scenario():
            runtime = BrowserRuntime()
            calls = []

            async def stop_action():
                calls.append("stopped")

            await runtime.schedule_profile_stop("profile-1", 1, stop_action)
            async with runtime.profile_lock("profile-1"):
                pass
            await asyncio.sleep(0.05)
            self.assertEqual(calls, [])
            await runtime.shutdown()

        asyncio.run(scenario())

    def test_stop_profile_now_cancels_scheduled_stop(self):
        async def scenario():
            runtime = BrowserRuntime()
            calls = []

            async def delayed_stop():
                calls.append("delayed")

            async def immediate_stop():
                calls.append("immediate")

            await runtime.schedule_profile_stop("profile-1", 5, delayed_stop)
            result = await runtime.stop_profile_now("profile-1", immediate_stop)

            self.assertTrue(result)
            self.assertEqual(calls, ["immediate"])
            await asyncio.sleep(0.05)
            self.assertEqual(calls, ["immediate"])
            await runtime.shutdown()

        asyncio.run(scenario())

    def test_shutdown_cancels_all_pending_delayed_stops(self):
        async def scenario():
            runtime = BrowserRuntime()
            fired = asyncio.Event()

            async def stop_action():
                fired.set()

            await runtime.schedule_profile_stop("profile-1", 5, stop_action)
            await runtime.shutdown()
            await asyncio.sleep(0.05)
            self.assertFalse(fired.is_set())

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
