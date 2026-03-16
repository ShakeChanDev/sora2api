"""Utilities for redacting secrets from logs and admin responses."""
import hashlib
import json
from typing import Any, Optional

SENSITIVE_KEYS = {
    "authorization",
    "access_token",
    "token",
    "st",
    "rt",
    "session_token",
    "refresh_token",
    "cookie",
    "cookie_header",
    "openai-sentinel-token",
    "sentinel_token",
    "client_id",
}


def mask_secret(value: Optional[str], visible_prefix: int = 4, visible_suffix: int = 4) -> Optional[str]:
    """Mask a secret while keeping a small preview for debugging."""
    if value is None:
        return None
    if len(value) <= visible_prefix + visible_suffix:
        return "*" * len(value)
    return f"{value[:visible_prefix]}...{value[-visible_suffix:]}"


def fingerprint_text(value: Any) -> Optional[str]:
    """Generate a stable, non-reversible fingerprint for structured logging."""
    if value is None:
        return None
    if not isinstance(value, str):
        value = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    return digest[:16]


def _sanitize_string(value: str, key_hint: Optional[str] = None) -> str:
    lowered = (key_hint or "").lower()

    if lowered == "authorization" and value.startswith("Bearer "):
        return f"Bearer {mask_secret(value[7:])}"

    if lowered in SENSITIVE_KEYS:
        return mask_secret(value) or ""

    if value.startswith("Bearer "):
        return f"Bearer {mask_secret(value[7:])}"

    if "__Secure-next-auth.session-token=" in value or "oai-did=" in value:
        parts = []
        for cookie in value.split(";"):
            cookie = cookie.strip()
            if "=" not in cookie:
                parts.append(cookie)
                continue
            name, raw_value = cookie.split("=", 1)
            name_lower = name.strip().lower()
            if name_lower in {"__secure-next-auth.session-token", "oai-did", "__cf_bm", "cf_clearance", "oai-sc"}:
                parts.append(f"{name}={mask_secret(raw_value.strip())}")
            else:
                parts.append(cookie)
        return "; ".join(parts)

    if len(value) > 48 and ("eyJ" in value[:8] or value.count(".") >= 2):
        return mask_secret(value) or ""

    return value


def sanitize_value(value: Any, key_hint: Optional[str] = None) -> Any:
    """Recursively sanitize secrets from nested structures."""
    if value is None:
        return None

    if isinstance(value, dict):
        return {key: sanitize_value(item, key) for key, item in value.items()}

    if isinstance(value, list):
        return [sanitize_value(item, key_hint) for item in value]

    if isinstance(value, tuple):
        return [sanitize_value(item, key_hint) for item in value]

    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith("{") or stripped.startswith("["):
            try:
                parsed = json.loads(stripped)
                return sanitize_value(parsed, key_hint)
            except Exception:
                pass
        return _sanitize_string(value, key_hint)

    return value


def sanitize_json_text(value: Optional[str]) -> Optional[str]:
    """Sanitize a JSON-serializable text blob while preserving readability."""
    if value is None:
        return None
    sanitized = sanitize_value(value)
    if isinstance(sanitized, str):
        return sanitized
    return json.dumps(sanitized, ensure_ascii=False)
