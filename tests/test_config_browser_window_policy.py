"""Tests for browser window lifecycle configuration."""
import copy
import unittest

from src.core.config import config


class BrowserWindowConfigTests(unittest.TestCase):
    def setUp(self):
        self._browser_config = copy.deepcopy(config._config.get("browser", {}))

    def tearDown(self):
        config._config["browser"] = self._browser_config

    def test_window_policy_defaults_to_persistent_when_missing(self):
        config._config.setdefault("browser", {}).pop("window_policy", None)
        config._config.setdefault("browser", {}).pop("failure_retention_seconds", None)

        self.assertEqual(config.browser_window_policy, "persistent")
        self.assertEqual(config.browser_failure_retention_seconds, 900)

    def test_window_policy_reads_explicit_auto_close_values(self):
        config._config.setdefault("browser", {})["window_policy"] = "auto_close"
        config._config.setdefault("browser", {})["failure_retention_seconds"] = 900

        self.assertEqual(config.browser_window_policy, "auto_close")
        self.assertEqual(config.browser_failure_retention_seconds, 900)


if __name__ == "__main__":
    unittest.main()
