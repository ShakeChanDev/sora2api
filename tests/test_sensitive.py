import unittest

from src.core.sensitive import mask_secret, sanitize_json_text, sanitize_value


class SensitiveUtilsTests(unittest.TestCase):
    def test_mask_secret_keeps_preview_only(self):
        self.assertEqual(mask_secret("abcdefghijklmnop"), "abcd...mnop")

    def test_sanitize_value_masks_nested_tokens_and_cookies(self):
        payload = {
            "Authorization": "Bearer abcdefghijklmnop",
            "cookie_header": "__Secure-next-auth.session-token=very-secret-token; oai-did=device-id",
            "nested": {"access_token": "eyJ.header.payload.signature"},
        }

        sanitized = sanitize_value(payload)

        self.assertEqual(sanitized["Authorization"], "Bearer abcd...mnop")
        self.assertNotEqual(sanitized["cookie_header"], payload["cookie_header"])
        self.assertNotIn("very-secret-token", sanitized["cookie_header"])
        self.assertNotIn("device-id", sanitized["cookie_header"])
        self.assertNotEqual(
            sanitized["nested"]["access_token"],
            "eyJ.header.payload.signature",
        )

    def test_sanitize_json_text_preserves_json_shape(self):
        raw = '{"refresh_token":"sensitive-refresh-token","ok":true}'
        sanitized = sanitize_json_text(raw)

        self.assertIn('"ok": true', sanitized)
        self.assertNotIn("sensitive-refresh-token", sanitized)


if __name__ == "__main__":
    unittest.main()
