"""Application secret encryption helpers."""
from __future__ import annotations

import base64
import hashlib
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken


class SecretCodec:
    """Versioned secret encoder/decoder backed by Fernet."""

    VERSION_PREFIX = "enc:v1:"

    def __init__(self):
        self._fernet: Optional[Fernet] = None
        self._raw_key: Optional[str] = None

    def configure(self, raw_key: Optional[str]):
        """Configure codec from environment or configuration value."""
        self._raw_key = (raw_key or "").strip() or None
        self._fernet = None
        if not self._raw_key:
            return
        try:
            key_bytes = self._raw_key.encode("utf-8")
            try:
                self._fernet = Fernet(key_bytes)
            except Exception:
                derived = base64.urlsafe_b64encode(hashlib.sha256(key_bytes).digest())
                self._fernet = Fernet(derived)
        except Exception:
            self._fernet = None

    @property
    def is_configured(self) -> bool:
        return self._fernet is not None

    def hash_secret(self, value: Optional[str]) -> Optional[str]:
        if not value:
            return None
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def encrypt(self, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        if not value:
            return value
        if value.startswith(self.VERSION_PREFIX):
            return value
        if not self._fernet:
            return value
        token = self._fernet.encrypt(value.encode("utf-8")).decode("utf-8")
        return f"{self.VERSION_PREFIX}{token}"

    def decrypt(self, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        if not value:
            return value
        if not value.startswith(self.VERSION_PREFIX):
            return value
        if not self._fernet:
            raise RuntimeError("Encrypted secret present but SORA2API_SECRET_KEY is not configured")
        token = value[len(self.VERSION_PREFIX):]
        try:
            return self._fernet.decrypt(token.encode("utf-8")).decode("utf-8")
        except InvalidToken as exc:
            raise RuntimeError("Failed to decrypt secret with configured SORA2API_SECRET_KEY") from exc


secret_codec = SecretCodec()
