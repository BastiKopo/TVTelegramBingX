"""Configuration helpers for the Telegram bot runtime."""
from __future__ import annotations

import json
from functools import lru_cache

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class BotSettings(BaseSettings):
    """Environment-driven settings for the Telegram bot."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    telegram_bot_token: str = Field(..., alias="TELEGRAM_BOT_TOKEN")
    telegram_admin_ids: str | None = Field(default=None, alias="TELEGRAM_ADMIN_IDS")
    admin_ids: set[int] = Field(default_factory=set)
    backend_base_url: str = Field("http://localhost:8000", alias="BACKEND_BASE_URL")
    request_timeout: float = Field(10.0, alias="BOT_BACKEND_TIMEOUT", ge=1.0)
    report_limit: int = Field(5, alias="BOT_REPORT_LIMIT", ge=1)
    environment: str = Field("development", alias="ENVIRONMENT")
    telemetry_enabled: bool = Field(False, alias="TELEMETRY_ENABLED")
    telemetry_service_name: str = Field("tvtelegrambingx-bot", alias="TELEMETRY_SERVICE_NAME")
    telemetry_otlp_endpoint: str | None = Field(default=None, alias="TELEMETRY_OTLP_ENDPOINT")
    telemetry_otlp_headers: dict[str, str] | None = Field(
        default=None, alias="TELEMETRY_OTLP_HEADERS"
    )
    telemetry_sample_ratio: float = Field(
        0.1, alias="TELEMETRY_SAMPLE_RATIO", ge=0.0, le=1.0
    )
    metrics_enabled: bool = Field(True, alias="BOT_METRICS_ENABLED")
    metrics_host: str = Field("0.0.0.0", alias="BOT_METRICS_HOST")
    metrics_port: int = Field(9000, alias="BOT_METRICS_PORT", ge=1, le=65535)

    @model_validator(mode="after")
    def _parse_admins(self) -> "BotSettings":
        if not self.telegram_admin_ids:
            self.admin_ids: set[int] = set()
        else:
            ids: set[int] = set()
            for raw in str(self.telegram_admin_ids).replace(";", ",").split(","):
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    ids.add(int(raw))
                except ValueError as exc:  # pragma: no cover - validation edge case
                    raise ValueError(f"Invalid admin id '{raw}'") from exc
            self.admin_ids = ids
        return self

    @model_validator(mode="after")
    def _parse_headers(self) -> "BotSettings":
        if isinstance(self.telemetry_otlp_headers, str):
            try:
                self.telemetry_otlp_headers = json.loads(self.telemetry_otlp_headers)
            except json.JSONDecodeError as exc:  # pragma: no cover - validation guard
                raise ValueError(
                    "TELEMETRY_OTLP_HEADERS must be valid JSON key/value pairs"
                ) from exc
        return self


@lru_cache
def get_settings() -> BotSettings:
    """Return cached bot settings instance."""

    return BotSettings()  # type: ignore[call-arg]


__all__ = ["BotSettings", "get_settings"]
