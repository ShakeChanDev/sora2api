"""Tests for secret encryption helpers."""
import unittest

from src.core.secret_codec import SecretCodec


class SecretCodecTests(unittest.TestCase):
    """Verify secret encryption and hashing behavior."""

    def test_encrypt_decrypt_round_trip(self):
        codec = SecretCodec()
        codec.configure("unit-test-secret")
        encrypted = codec.encrypt("token-value")
        self.assertTrue(encrypted.startswith("enc:v1:"))
        self.assertEqual(codec.decrypt(encrypted), "token-value")

    def test_plaintext_passthrough_without_key(self):
        codec = SecretCodec()
        codec.configure("")
        self.assertEqual(codec.encrypt("token-value"), "token-value")
        self.assertEqual(codec.decrypt("token-value"), "token-value")

    def test_hash_is_stable(self):
        codec = SecretCodec()
        self.assertEqual(codec.hash_secret("abc"), codec.hash_secret("abc"))
        self.assertNotEqual(codec.hash_secret("abc"), codec.hash_secret("abcd"))


if __name__ == "__main__":
    unittest.main()
