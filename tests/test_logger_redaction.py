"""Regression tests for secret redaction."""
import json
import unittest

from src.core.logger import debug_logger


class LoggerRedactionTests(unittest.TestCase):
    """Ensure sensitive values are redacted before logging/admin exposure."""

    def test_sanitize_value_redacts_known_secret_keys(self):
        payload = {
            "access_token": "abc123456789xyz",
            "session_token": "st-secret-value",
            "refresh_token": "rt-secret-value",
            "cookie": "__Secure-next-auth.session-token=super-secret",
            "openai-sentinel-token": "sentinel-secret",
            "oai-device-id": "device-secret",
            "nested": {"Authorization": "Bearer jwt-token-value"},
        }

        sanitized = debug_logger.sanitize_value(payload)

        self.assertNotEqual(payload["access_token"], sanitized["access_token"])
        self.assertIn("[REDACTED]", debug_logger.sanitize_value("Bearer jwt-token-value"))
        self.assertIn("[REDACTED]", sanitized["cookie"])
        self.assertEqual(sanitized["nested"]["Authorization"], "[REDACTED]")

    def test_sanitize_json_text_redacts_access_token(self):
        raw = json.dumps({"accessToken": "jwt-secret", "refresh_token": "rt-secret"})
        sanitized = debug_logger.sanitize_json_text(raw)

        self.assertIn("[REDACTED]", sanitized)
        self.assertNotIn("jwt-secret", sanitized)
        self.assertNotIn("rt-secret", sanitized)


if __name__ == "__main__":
    unittest.main()
