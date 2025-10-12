"""Configuration helpers for the TVTelegramBingX bot."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional


def _read_env(name: str, default: Optional[str] = None) -> Optional[str]:
    """Read an environment variable with optional `_FILE` indirection."""
    file_key = f"{name}_FILE"
    if file_path := os.getenv(file_key):
        try:
            with open(file_path, "r", encoding="utf-8") as fp:
                return fp.read().strip()
        except OSError:
            # Fall back to the direct variable when the file cannot be read.
            pass
    value = os.getenv(name, default)
    if isinstance(value, str):
        value = value.strip()
    return value


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str
    telegram_chat_id: str
    tradingview_secret: Optional[str]
    bingx_api_key: Optional[str]
    bingx_api_secret: Optional[str]
    bingx_base_url: str
    bingx_recv_window: int
    dry_run: bool
    tradingview_webhook_enabled: bool
    tradingview_host: str
    tradingview_port: int


def load_settings() -> Settings:
    """Load application settings from environment variables."""
    def _read_first(*keys: str, default: Optional[str] = None) -> Optional[str]:
        for key in keys:
            value = _read_env(key)
            if value:
                return value
        return default

    token = _read_first("TELEGRAM_BOT_TOKEN", "TELEGRAM_TOKEN")
    chat_id = _read_first("TELEGRAM_CHAT_ID")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is required")
    if not chat_id:
        raise RuntimeError("TELEGRAM_CHAT_ID is required")

    secret = _read_first("TRADINGVIEW_WEBHOOK_SECRET", "WEBHOOK_SECRET")
    bingx_key = _read_first("BINGX_API_KEY", "BINGX_KEY")
    bingx_secret = _read_first("BINGX_API_SECRET", "BINGX_SECRET")
    base_url = (
        _read_first("BINGX_BASE_URL", "BINGX_BASE")
        or "https://open-api.bingx.com"
    )
    recv_window = int(_read_env("BINGX_RECV_WINDOW", "5000") or "5000")

    dry_run = (_read_env("DRY_RUN", "0") or "0").lower() in {"1", "true", "yes", "on"}
    webhook_enabled = (
        (_read_first("TRADINGVIEW_WEBHOOK_ENABLED") or _read_env("ENABLE_WEBHOOK") or "0")
        .lower()
        in {"1", "true", "yes", "on"}
    )
    host = _read_first("TRADINGVIEW_WEBHOOK_HOST") or "0.0.0.0"
    port = int(_read_first("TRADINGVIEW_WEBHOOK_PORT", "PORT", default="8443") or "8443")

    return Settings(
        telegram_bot_token=token,
        telegram_chat_id=chat_id,
        tradingview_secret=secret,
        bingx_api_key=bingx_key,
        bingx_api_secret=bingx_secret,
        bingx_base_url=base_url,
        bingx_recv_window=recv_window,
        dry_run=dry_run,
        tradingview_webhook_enabled=webhook_enabled,
        tradingview_host=host,
        tradingview_port=port,
    )
