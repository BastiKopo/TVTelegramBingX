"""FastAPI application exposing a TradingView webhook endpoint."""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
from collections.abc import Mapping, Sequence
from functools import lru_cache
from json import JSONDecodeError
from typing import Any, Dict

from fastapi import FastAPI, Header, HTTPException, Request, status
from pydantic import BaseModel, ValidationError
from telegram import Bot
from telegram.error import TelegramError

from config import Settings, get_settings

LOGGER = logging.getLogger(__name__)

app = FastAPI(title="TVTelegramBingX Webhook Server")


class TradingViewAlert(BaseModel):
    """Subset of common TradingView alert fields."""

    secret: str | None = None
    message: str | None = None
    ticker: str | None = None
    symbol: str | None = None
    action: str | None = None
    direction: str | None = None
    price: float | None = None
    strategy: Dict[str, Any] | None = None

    class Config:
        extra = "allow"


_BOT_LOCK = asyncio.Lock()
_BOT: Bot | None = None


@lru_cache(maxsize=1)
def _cached_settings() -> Settings:
    """Return cached application settings."""

    return get_settings()


def _verify_secret(provided: str | None, expected: str | None) -> None:
    """Raise an ``HTTPException`` when the shared secret is invalid."""

    if not expected:
        LOGGER.error("TradingView webhook secret is not configured")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="TradingView webhook secret is not configured.",
        )

    if not provided or not hmac.compare_digest(provided, expected):
        LOGGER.warning("TradingView webhook rejected due to invalid secret")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid TradingView secret.")


async def _get_bot(settings: Settings) -> Bot:
    """Return a shared Telegram ``Bot`` instance."""

    global _BOT
    if _BOT and getattr(_BOT, "token", None) == settings.telegram_bot_token:
        return _BOT

    async with _BOT_LOCK:
        if _BOT is None or getattr(_BOT, "token", None) != settings.telegram_bot_token:
            _BOT = Bot(token=settings.telegram_bot_token)
    return _BOT


def _format_value(value: Any) -> str:
    """Convert a Python value to a readable string for Telegram messages."""

    if isinstance(value, (str, int, float, bool)) or value is None:
        return str(value)

    if isinstance(value, (Mapping, Sequence)) and not isinstance(value, (str, bytes, bytearray)):
        try:
            return json.dumps(value, ensure_ascii=False, indent=2)
        except TypeError:
            return repr(value)

    return repr(value)


def _render_alert_message(payload: dict[str, Any]) -> str:
    """Return a formatted message describing the TradingView alert."""

    payload = dict(payload)  # Shallow copy to safely modify the payload.
    headline_parts: list[str] = []

    action = payload.get("action") or payload.get("direction")
    if action:
        headline_parts.append(str(action).upper())

    symbol = payload.get("symbol") or payload.get("ticker")
    if symbol:
        headline_parts.append(str(symbol))

    price = payload.get("price")
    if price is not None:
        headline_parts.append(f"@ {price}")

    message_lines = ["🚨 TradingView alert received"]
    if headline_parts:
        message_lines.append(" ".join(headline_parts))

    user_message = payload.pop("message", None)
    if user_message:
        message_lines.append("")
        message_lines.append(str(user_message))

    if payload:
        message_lines.append("")
        message_lines.append("Details:")
        for key in sorted(payload):
            if key in {"secret"}:
                continue
            value = payload[key]
            formatted = _format_value(value)
            message_lines.append(f"• {key}: {formatted}")

    return "\n".join(message_lines)


async def _forward_to_telegram(*, settings: Settings, alert_payload: dict[str, Any]) -> None:
    """Send the alert payload to the configured Telegram chat if available."""

    chat_id = settings.telegram_alert_chat_id
    if not chat_id:
        LOGGER.debug("TELEGRAM_ALERT_CHAT_ID not configured; skipping Telegram notification")
        return

    bot = await _get_bot(settings)
    message_text = _render_alert_message(alert_payload)

    try:
        await bot.send_message(chat_id=chat_id, text=message_text)
    except TelegramError as exc:
        LOGGER.exception("Failed to forward TradingView alert to Telegram: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to forward alert to Telegram.",
        ) from exc


@app.post("/tradingview-webhook")
async def tradingview_webhook(
    request: Request, x_tradingview_secret: str | None = Header(default=None)
) -> dict[str, str]:
    """Validate and process TradingView webhook requests."""

    try:
        raw_payload = await request.json()
    except JSONDecodeError as exc:
        LOGGER.warning("Received TradingView webhook with invalid JSON: %s", exc)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Payload must be valid JSON.") from exc

    if not isinstance(raw_payload, dict):
        LOGGER.warning("TradingView webhook payload must be a JSON object, received %s", type(raw_payload).__name__)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Payload must be a JSON object.")

    provided_secret_raw = x_tradingview_secret or raw_payload.get("secret")
    provided_secret = str(provided_secret_raw) if provided_secret_raw is not None else None

    try:
        settings = _cached_settings()
    except RuntimeError as exc:
        LOGGER.error("Configuration error while handling TradingView webhook: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Webhook server configuration error.",
        ) from exc

    _verify_secret(provided_secret, settings.tradingview_webhook_secret)

    try:
        alert = TradingViewAlert.parse_obj(raw_payload)
    except ValidationError as exc:
        LOGGER.warning("TradingView webhook payload validation failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Payload validation failed.",
        ) from exc

    sanitized_payload = alert.dict(exclude_none=True, exclude={"secret"})

    LOGGER.info(
        "Accepted TradingView alert for symbol %s", sanitized_payload.get("symbol") or sanitized_payload.get("ticker")
    )

    await _forward_to_telegram(settings=settings, alert_payload=sanitized_payload)

    return {"status": "accepted"}
