"""Adapter settings."""
from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings for the Polo adapter service."""

    shared_api_key: str = Field(default="han1234", alias="POLO_SHARED_API_KEY")
    main_base_url: str = Field(default="http://127.0.0.1:8000", alias="POLO_MAIN_BASE_URL")
    db_path: str = Field(default="data/hancat.db", alias="POLO_DB_PATH")
    adapter_host: str = Field(default="0.0.0.0", alias="POLO_ADAPTER_HOST")
    adapter_port: int = Field(default=8010, alias="POLO_ADAPTER_PORT")
    create_timeout_seconds: float = Field(default=5.0, alias="POLO_CREATE_TIMEOUT_SECONDS")
    image_download_timeout_seconds: float = Field(default=10.0, alias="POLO_IMAGE_DOWNLOAD_TIMEOUT_SECONDS")
    image_max_bytes: int = Field(default=10 * 1024 * 1024, alias="POLO_IMAGE_MAX_BYTES")
    image_max_redirects: int = Field(default=3, alias="POLO_IMAGE_MAX_REDIRECTS")
    main_local_tz: str = Field(default="Asia/Shanghai", alias="POLO_MAIN_LOCAL_TZ")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        populate_by_name=True,
    )

    @property
    def db_path_obj(self) -> Path:
        return Path(self.db_path).expanduser().resolve()
