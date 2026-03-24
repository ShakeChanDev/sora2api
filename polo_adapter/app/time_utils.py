"""SQLite timestamp parsing utilities."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo


def _parse_timestamp(value: Optional[str | datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value

    raw = str(value).strip()
    if not raw:
        return None

    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"

    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        pass

    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


def sqlite_utc_to_unix(value: Optional[str | datetime]) -> Optional[int]:
    """Parse SQLite CURRENT_TIMESTAMP values as UTC seconds."""

    parsed = _parse_timestamp(value)
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    else:
        parsed = parsed.astimezone(timezone.utc)
    return int(parsed.timestamp())


def sqlite_local_to_unix(value: Optional[str | datetime], timezone_name: str) -> Optional[int]:
    """Parse naive SQLite timestamps using the main service local timezone."""

    parsed = _parse_timestamp(value)
    if parsed is None:
        return None

    target_tz = ZoneInfo(timezone_name)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=target_tz)
    else:
        parsed = parsed.astimezone(target_tz)
    return int(parsed.timestamp())
