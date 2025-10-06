"""Application configuration utilities."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import cast


def load_dotenv(dotenv_path: str | None = None) -> None:
    """Load environment variables from a ``.env`` file if present.

    Parameters
    ----------
    dotenv_path:
        Optional path to a custom ``.env`` file. Defaults to ``.env`` in the
        project root when not provided.
    """

    path = Path(dotenv_path or ".env")
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        if "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"')
        os.environ.setdefault(key, value)


@dataclass(frozen=True)
class Settings:
    """Container for application-wide configuration values."""

    telegram_bot_token: str
    bingx_api_key: str
    bingx_api_secret: str
    bingx_base_url: str = "https://open-api.bingx.com"
    telegram_chat_id: str | None = None
    tradingview_webhook_enabled: bool = False
    tradingview_webhook_secret: str | None = None
    tls_cert_path: Path | None = None
    tls_key_path: Path | None = None


def get_settings(dotenv_path: str | None = None) -> Settings:
    """Return the application settings.

    Loading order:
    1. Existing environment variables.
    2. Variables declared in ``.env`` (without overriding existing values).

    Parameters
    ----------
    dotenv_path:
        Optional path to a custom ``.env`` file.

    Raises
    ------
    RuntimeError
        If required configuration values are missing.
    """

    load_dotenv(dotenv_path=dotenv_path)

    token = os.getenv("TELEGRAM_BOT_TOKEN")
    api_key = os.getenv("BINGX_API_KEY")
    api_secret = os.getenv("BINGX_API_SECRET")
    base_url = os.getenv("BINGX_BASE_URL", "https://open-api.bingx.com")
    telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID")
    webhook_enabled = os.getenv("TRADINGVIEW_WEBHOOK_ENABLED", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    webhook_secret = (os.getenv("TRADINGVIEW_WEBHOOK_SECRET") or "").strip() or None
    tls_cert_path_env = (os.getenv("TLS_CERT_PATH") or "").strip() or None
    tls_key_path_env = (os.getenv("TLS_KEY_PATH") or "").strip() or None

    missing = [
        name
        for name, value in {
            "TELEGRAM_BOT_TOKEN": token,
            "BINGX_API_KEY": api_key,
            "BINGX_API_SECRET": api_secret,
        }.items()
        if not value
    ]

    if missing:
        formatted = ", ".join(missing)
        raise RuntimeError(
            f"Missing required configuration: {formatted}. "
            "Set the environment variable(s) or add them to the .env file."
        )

    if webhook_enabled:
        webhook_missing = [
            name
            for name, value in {
                "TRADINGVIEW_WEBHOOK_SECRET": webhook_secret,
                "TLS_CERT_PATH": tls_cert_path_env,
                "TLS_KEY_PATH": tls_key_path_env,
            }.items()
            if not value
        ]
        if webhook_missing:
            formatted = ", ".join(webhook_missing)
            raise RuntimeError(
                "TradingView webhook is enabled but missing configuration: "
                f"{formatted}. Set the environment variable(s) before starting the service."
            )

    return Settings(
        telegram_bot_token=cast(str, token),
        bingx_api_key=cast(str, api_key),
        bingx_api_secret=cast(str, api_secret),
        bingx_base_url=base_url,
        telegram_chat_id=telegram_chat_id,
        tradingview_webhook_enabled=webhook_enabled,
        tradingview_webhook_secret=webhook_secret,
        tls_cert_path=Path(tls_cert_path_env) if tls_cert_path_env else None,
        tls_key_path=Path(tls_key_path_env) if tls_key_path_env else None,
    )


__all__ = ["Settings", "get_settings", "load_dotenv"]
