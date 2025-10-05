"""Application configuration utilities."""
from functools import lru_cache
from typing import Literal, Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central application settings loaded from environment variables."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    tradingview_token: str = Field(..., alias="TRADINGVIEW_WEBHOOK_TOKEN")
    database_url: str = Field("sqlite+aiosqlite:///./storage.db", alias="DATABASE_URL")

    telegram_bot_token: Optional[str] = Field(default=None, alias="TELEGRAM_BOT_TOKEN")
    telegram_admin_ids: Optional[str] = Field(default=None, alias="TELEGRAM_ADMIN_IDS")

    bingx_api_key: Optional[str] = Field(default=None, alias="BINGX_API_KEY")
    bingx_api_secret: Optional[str] = Field(default=None, alias="BINGX_API_SECRET")
    bingx_subaccount_id: Optional[str] = Field(default=None, alias="BINGX_SUBACCOUNT_ID")

    default_margin_mode: Literal["isolated", "cross"] = Field("isolated", alias="DEFAULT_MARGIN_MODE")
    default_leverage: int = Field(5, alias="DEFAULT_LEVERAGE", ge=1)

    broker_host: Optional[str] = Field(default=None, alias="BROKER_HOST")
    broker_port: int = Field(5672, alias="BROKER_PORT", ge=1, le=65535)
    broker_username: str = Field("guest", alias="BROKER_USERNAME")
    broker_password: str = Field("guest", alias="BROKER_PASSWORD")
    broker_virtual_host: str = Field("/", alias="BROKER_VHOST")
    broker_exchange: str = Field("signals", alias="BROKER_EXCHANGE")
    broker_validated_routing_key: str = Field(
        "signals.validated", alias="BROKER_VALIDATED_ROUTING_KEY"
    )


@lru_cache
def get_settings() -> Settings:
    """Return cached Settings instance."""

    return Settings()  # type: ignore[call-arg]


__all__ = ["Settings", "get_settings"]
