"""Application configuration utilities."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
def _parse_bool(value: str | None) -> bool:
    if value is None:
        return False
    token = value.strip().lower()
    return token in {"1", "true", "yes", "on"}


def _normalise_symbol_token(value: str) -> str:
    text = value.strip().upper()
    if not text:
        return text
    if ":" in text:
        text = text.rsplit(":", 1)[-1]
    text = text.replace("/", "-").replace("_", "-")
    if "-" in text:
        parts = [segment for segment in text.split("-") if segment]
        if len(parts) >= 2:
            return f"{parts[0]}-{parts[1]}"
        return text
    for quote in ("USDT", "USDC", "BUSD", "USDD", "USD"):
        if text.endswith(quote) and len(text) > len(quote):
            return f"{text[:-len(quote)]}-{quote}"
    return text


def _parse_symbol_thresholds(raw: str | None) -> dict[str, float]:
    if not raw:
        return {}
    result: dict[str, float] = {}
    for item in raw.split(","):
        token = item.strip()
        if not token or ":" not in token:
            continue
        symbol_part, value_part = token.split(":", 1)
        symbol = _normalise_symbol_token(symbol_part)
        try:
            value = float(value_part)
        except ValueError:
            continue
        if value < 0:
            continue
        result[symbol] = value
    return result


def _parse_symbol_list(raw: str | None) -> tuple[str, ...]:
    if not raw:
        return ()
    symbols: list[str] = []
    for item in raw.split(","):
        token = _normalise_symbol_token(item)
        if token:
            symbols.append(token)
    return tuple(dict.fromkeys(symbols))


def _parse_symbol_meta(raw: str | None) -> dict[str, dict[str, str]]:
    if not raw:
        return {}

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}

    if not isinstance(payload, Mapping):
        return {}

    result: dict[str, dict[str, str]] = {}
    for symbol_key, meta in payload.items():
        if not isinstance(meta, Mapping):
            continue
        symbol = _normalise_symbol_token(str(symbol_key))
        if not symbol:
            continue
        entry: dict[str, str] = {}
        step_value = meta.get("stepSize") or meta.get("step_size")
        if step_value is not None:
            entry["stepSize"] = str(step_value)
        min_qty_value = meta.get("minQty") or meta.get("min_qty")
        if min_qty_value is not None:
            entry["minQty"] = str(min_qty_value)
        min_notional_value = meta.get("minNotional") or meta.get("min_notional")
        if min_notional_value is not None:
            entry["minNotional"] = str(min_notional_value)
        if entry:
            result[symbol] = entry

    return result
from pathlib import Path
from typing import Mapping, cast


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
    bingx_recv_window: int = 5_000
    position_mode: str = "hedge"
    default_leverage: int = 10
    default_time_in_force: str = "GTC"
    dry_run: bool = False
    symbol_whitelist: tuple[str, ...] = ()
    symbol_min_qty: dict[str, float] | None = None
    symbol_max_qty: dict[str, float] | None = None
    symbol_meta: dict[str, dict[str, str]] | None = None
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
    base_url = (
        os.getenv("BINGX_BASE")
        or os.getenv("BINGX_BASE_URL")
        or "https://open-api.bingx.com"
    )
    telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID")
    webhook_enabled = _parse_bool(os.getenv("TRADINGVIEW_WEBHOOK_ENABLED"))
    webhook_secret = (os.getenv("TRADINGVIEW_WEBHOOK_SECRET") or "").strip() or None
    tls_cert_path_env = (os.getenv("TLS_CERT_PATH") or "").strip() or None
    tls_key_path_env = (os.getenv("TLS_KEY_PATH") or "").strip() or None
    recv_window_env = os.getenv("BINGX_RECV_WINDOW")
    position_mode_env = (os.getenv("POSITION_MODE") or "hedge").strip().lower()
    dry_run = _parse_bool(os.getenv("DRY_RUN"))
    symbol_whitelist = _parse_symbol_list(os.getenv("SYMBOL_WHITELIST"))
    min_qty = _parse_symbol_thresholds(os.getenv("SYMBOL_MIN_QTY"))
    max_qty = _parse_symbol_thresholds(os.getenv("SYMBOL_MAX_QTY"))
    symbol_meta = _parse_symbol_meta(os.getenv("SYMBOL_META"))
    default_leverage_env = os.getenv("DEFAULT_LEVERAGE")
    default_tif_env = (os.getenv("DEFAULT_TIF") or "GTC").strip().upper() or "GTC"

    try:
        recv_window = int(recv_window_env) if recv_window_env else 5_000
    except ValueError as exc:
        raise RuntimeError("BINGX_RECV_WINDOW must be an integer value.") from exc

    position_mode = "hedge" if position_mode_env not in {"hedge", "oneway"} else position_mode_env

    try:
        default_leverage = int(default_leverage_env) if default_leverage_env else 10
    except ValueError as exc:
        raise RuntimeError("DEFAULT_LEVERAGE must be a positive integer.") from exc

    if default_leverage <= 0:
        raise RuntimeError("DEFAULT_LEVERAGE must be a positive integer.")

    default_tif = default_tif_env if default_tif_env in {"GTC", "IOC", "FOK"} else "GTC"

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
        bingx_recv_window=recv_window,
        position_mode=position_mode,
        default_leverage=default_leverage,
        default_time_in_force=default_tif,
        dry_run=dry_run,
        symbol_whitelist=symbol_whitelist,
        symbol_min_qty=min_qty or None,
        symbol_max_qty=max_qty or None,
        symbol_meta=symbol_meta or None,
        telegram_chat_id=telegram_chat_id,
        tradingview_webhook_enabled=webhook_enabled,
        tradingview_webhook_secret=webhook_secret,
        tls_cert_path=Path(tls_cert_path_env) if tls_cert_path_env else None,
        tls_key_path=Path(tls_key_path_env) if tls_key_path_env else None,
    )


__all__ = ["Settings", "get_settings", "load_dotenv"]
