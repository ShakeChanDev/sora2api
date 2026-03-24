"""External Polo model names to internal main-service model names."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ModelMapping:
    """Mapping metadata for a public model."""

    public_name: str
    main_service_name: str
    supports_references: bool = True


MODEL_MAPPINGS: dict[str, ModelMapping] = {
    "sora-2-portrait-10s": ModelMapping("sora-2-portrait-10s", "sora2-portrait-10s"),
    "sora-2-landscape-10s": ModelMapping("sora-2-landscape-10s", "sora2-landscape-10s"),
    "sora-2-portrait-15s": ModelMapping("sora-2-portrait-15s", "sora2-portrait-15s"),
    "sora-2-landscape-15s": ModelMapping("sora-2-landscape-15s", "sora2-landscape-15s"),
    "sora-2-portrait-25s": ModelMapping("sora-2-portrait-25s", "sora2-portrait-25s"),
    "sora-2-landscape-25s": ModelMapping("sora-2-landscape-25s", "sora2-landscape-25s"),
    "sora-2-pro-portrait-10s": ModelMapping("sora-2-pro-portrait-10s", "sora2pro-portrait-10s"),
    "sora-2-pro-landscape-10s": ModelMapping("sora-2-pro-landscape-10s", "sora2pro-landscape-10s"),
    "sora-2-pro-portrait-15s": ModelMapping("sora-2-pro-portrait-15s", "sora2pro-portrait-15s"),
    "sora-2-pro-landscape-15s": ModelMapping("sora-2-pro-landscape-15s", "sora2pro-landscape-15s"),
}

DEFAULT_PUBLIC_MODEL = "sora-2-portrait-15s"


def resolve_model(public_name: str | None) -> ModelMapping:
    """Resolve a public model name or raise KeyError."""

    candidate = public_name or DEFAULT_PUBLIC_MODEL
    return MODEL_MAPPINGS[candidate]
