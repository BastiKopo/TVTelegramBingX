"""Application configuration utilities."""
from __future__ import annotations

import json
from functools import lru_cache
from typing import Literal, Optional
from urllib.parse import quote_plus

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central application settings loaded from environment variables."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    tradingview_token: str = Field(..., alias="TRADINGVIEW_WEBHOOK_TOKEN")
    database_url: Optional[str] = Field(default=None, alias="DATABASE_URL")
    database_host: str = Field("localhost", alias="DATABASE_HOST")
    database_port: int = Field(5432, alias="DATABASE_PORT", ge=1, le=65535)
    database_name: str = Field("tvtelegrambingx", alias="DATABASE_NAME")
    database_user: str = Field("postgres", alias="DATABASE_USER")
    database_password: str = Field("postgres", alias="DATABASE_PASSWORD")

    telegram_bot_token: Optional[str] = Field(default=None, alias="TELEGRAM_BOT_TOKEN")
    telegram_chat_id: Optional[str] = Field(default=None, alias="TELEGRAM_CHAT_ID")
    telegram_admin_ids: Optional[str] = Field(default=None, alias="TELEGRAM_ADMIN_IDS")

    bingx_api_key: Optional[str] = Field(default=None, alias="BINGX_API_KEY")
    bingx_api_secret: Optional[str] = Field(default=None, alias="BINGX_API_SECRET")
    bingx_subaccount_id: Optional[str] = Field(default=None, alias="BINGX_SUBACCOUNT_ID")

    default_margin_mode: Literal["isolated", "cross"] = Field("isolated", alias="DEFAULT_MARGIN_MODE")
    default_leverage: int = Field(5, alias="DEFAULT_LEVERAGE", ge=1)

    trading_default_username: str = Field("system", alias="TRADING_DEFAULT_USERNAME")
    trading_default_session: str = Field("default", alias="TRADING_DEFAULT_SESSION")

    broker_host: Optional[str] = Field(default=None, alias="BROKER_HOST")
    broker_port: int = Field(5672, alias="BROKER_PORT", ge=1, le=65535)
    broker_username: str = Field("guest", alias="BROKER_USERNAME")
    broker_password: str = Field("guest", alias="BROKER_PASSWORD")
    broker_virtual_host: str = Field("/", alias="BROKER_VHOST")
    broker_exchange: str = Field("signals", alias="BROKER_EXCHANGE")
    broker_validated_routing_key: str = Field(
        "signals.validated", alias="BROKER_VALIDATED_ROUTING_KEY"
    )

    environment: str = Field("development", alias="ENVIRONMENT")
    force_https: bool = Field(True, alias="FORCE_HTTPS")
    allowed_hosts: list[str] = Field(default_factory=lambda: ["*"], alias="ALLOWED_HOSTS")

    telemetry_enabled: bool = Field(False, alias="TELEMETRY_ENABLED")
    telemetry_service_name: str = Field("tvtelegrambingx-backend", alias="TELEMETRY_SERVICE_NAME")
    telemetry_otlp_endpoint: Optional[str] = Field(default=None, alias="TELEMETRY_OTLP_ENDPOINT")
    telemetry_otlp_headers: dict[str, str] | None = Field(
        default=None, alias="TELEMETRY_OTLP_HEADERS"
    )
    telemetry_sample_ratio: float = Field(
        0.1, alias="TELEMETRY_SAMPLE_RATIO", ge=0.0, le=1.0
    )

    @model_validator(mode="after")
    def _populate_database_url(self) -> "Settings":
        """Ensure a PostgreSQL DSN is always available."""

        if not self.database_url:
            user = quote_plus(self.database_user)
            password = quote_plus(self.database_password)
            credentials = f"{user}:{password}" if password else user
            self.database_url = (
                f"postgresql+asyncpg://{credentials}@{self.database_host}:{self.database_port}/{self.database_name}"
            )
        return self

    @model_validator(mode="after")
    def _normalise_security_settings(self) -> "Settings":
        """Normalise host allow-lists and telemetry headers."""

        if isinstance(self.allowed_hosts, str):
            hosts = [
                host.strip()
                for host in self.allowed_hosts.replace(";", ",").split(",")
                if host.strip()
            ]
            self.allowed_hosts = hosts or ["*"]

        if isinstance(self.telemetry_otlp_headers, str):
            try:
                self.telemetry_otlp_headers = json.loads(self.telemetry_otlp_headers)
            except json.JSONDecodeError as exc:  # pragma: no cover - configuration error
                raise ValueError(
                    "TELEMETRY_OTLP_HEADERS must be valid JSON key/value pairs"
                ) from exc

        return self


@lru_cache
def get_settings() -> Settings:
    """Return cached Settings instance."""

    return Settings()  # type: ignore[call-arg]


__all__ = ["Settings", "get_settings"]
