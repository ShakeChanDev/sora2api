"""Tests for browser window lifecycle configuration."""
import copy
import unittest

from src.core.config import config


class BrowserWindowConfigTests(unittest.TestCase):
    def setUp(self):
        self._browser_config = copy.deepcopy(config._config.get("browser", {}))
        self._nst_browser_config = copy.deepcopy(config._config.get("nst_browser", {}))

    def tearDown(self):
        config._config["browser"] = self._browser_config
        config._config["nst_browser"] = self._nst_browser_config

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

    def test_nst_browser_api_key_reads_and_writes_runtime_value(self):
        config._config["nst_browser"] = {
            "base_url": "http://127.0.0.1:8848/api/v2",
            "api_key": "initial-key",
        }

        self.assertEqual(config.nst_browser_api_key, "initial-key")

        config.nst_browser_api_key = "updated-key"

        self.assertEqual(config.nst_browser_api_key, "updated-key")
        self.assertEqual(config._config["nst_browser"]["api_key"], "updated-key")


if __name__ == "__main__":
    unittest.main()
