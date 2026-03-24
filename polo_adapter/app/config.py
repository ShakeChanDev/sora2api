"""Configuration for the Polo adapter service."""
from __future__ import annotations

from pathlib import Path

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-driven settings for the adapter."""

    api_key: str = Field(
        ...,
        validation_alias=AliasChoices("POLO_ADAPTER_API_KEY", "POLO_SHARED_API_KEY"),
    )
    main_base_url: str = Field(
        ...,
        validation_alias=AliasChoices("POLO_ADAPTER_MAIN_BASE_URL", "POLO_MAIN_BASE_URL"),
    )
    sqlite_path: str = Field(
        "data/hancat.db",
        validation_alias=AliasChoices("POLO_ADAPTER_SQLITE_PATH", "POLO_DB_PATH"),
    )
    host: str = Field("0.0.0.0", validation_alias="POLO_ADAPTER_HOST")
    port: int = Field(8100, validation_alias="POLO_ADAPTER_PORT")
    task_id_wait_seconds: float = Field(
        5.0,
        validation_alias=AliasChoices("POLO_ADAPTER_TASK_ID_WAIT_SECONDS", "POLO_CREATE_TIMEOUT_SECONDS"),
    )
    image_timeout_seconds: float = Field(
        15.0,
        validation_alias=AliasChoices(
            "POLO_ADAPTER_IMAGE_TIMEOUT_SECONDS",
            "POLO_IMAGE_DOWNLOAD_TIMEOUT_SECONDS",
        ),
    )
    image_max_bytes: int = Field(
        10 * 1024 * 1024,
        validation_alias=AliasChoices("POLO_ADAPTER_IMAGE_MAX_BYTES", "POLO_IMAGE_MAX_BYTES"),
    )
    image_max_redirects: int = Field(
        3,
        validation_alias=AliasChoices("POLO_ADAPTER_IMAGE_MAX_REDIRECTS", "POLO_IMAGE_MAX_REDIRECTS"),
    )
    sqlite_busy_timeout_ms: int = Field(5000, validation_alias="POLO_ADAPTER_SQLITE_BUSY_TIMEOUT_MS")
    main_local_tz: str = Field(
        "Asia/Shanghai",
        validation_alias=AliasChoices("POLO_ADAPTER_MAIN_LOCAL_TZ", "POLO_MAIN_LOCAL_TZ"),
    )
    main_connect_timeout_seconds: float = Field(10.0, validation_alias="POLO_ADAPTER_MAIN_CONNECT_TIMEOUT_SECONDS")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator("api_key")
    @classmethod
    def validate_api_key(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("POLO_ADAPTER_API_KEY cannot be empty")
        return value

    @field_validator("main_base_url")
    @classmethod
    def normalize_main_base_url(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        if not value:
            raise ValueError("POLO_ADAPTER_MAIN_BASE_URL cannot be empty")
        return value

    @field_validator("sqlite_path")
    @classmethod
    def normalize_sqlite_path(cls, value: str) -> str:
        return value.strip() or "data/hancat.db"

    @field_validator("main_local_tz")
    @classmethod
    def normalize_main_local_tz(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("POLO_ADAPTER_MAIN_LOCAL_TZ cannot be empty")
        return value

    @property
    def sqlite_path_resolved(self) -> Path:
        return Path(self.sqlite_path).resolve()
