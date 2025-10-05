"""FastAPI application exposing a TradingView webhook endpoint."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, HTTPException, Request, status

from config import Settings, get_settings
from webhook.dispatcher import publish_alert

LOGGER = logging.getLogger(__name__)

_SECRET_HEADER_CANDIDATES = (
    "X-Tradingview-Secret",
    "X-TRADINGVIEW-SECRET",
    "X-Webhook-Secret",
)


def _extract_secret(request: Request, payload: Any) -> str | None:
    """Return the shared secret from headers or payload."""

    for header_name in _SECRET_HEADER_CANDIDATES:
        value = request.headers.get(header_name)
        if value:
            return value

    if isinstance(payload, dict):
        secret_candidate = payload.get("secret") or payload.get("password")
        if isinstance(secret_candidate, str):
            return secret_candidate

    return None


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create a FastAPI application wired to the alert dispatcher."""

    settings = settings or get_settings()
    if not settings.tradingview_webhook_enabled:
        raise RuntimeError(
            "TradingView webhook is disabled. Set TRADINGVIEW_WEBHOOK_ENABLED=true to enable it."
        )

    secret = settings.tradingview_webhook_secret
    if not secret:
        raise RuntimeError("TradingView webhook secret is not configured.")

    app = FastAPI(title="TVTelegramBingX TradingView Webhook")

    @app.post("/tradingview-webhook")
    async def tradingview_webhook(request: Request) -> dict[str, str]:
        try:
            payload = await request.json()
        except Exception as exc:  # pragma: no cover - FastAPI wraps request errors
            LOGGER.debug("Failed to decode webhook payload", exc_info=exc)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid JSON payload received.",
            ) from exc

        provided_secret = _extract_secret(request, payload)
        if provided_secret != secret:
            LOGGER.warning("Rejected webhook call due to invalid secret")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid webhook secret.",
            )

        if not isinstance(payload, dict):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Webhook payload must be a JSON object.",
            )

        await publish_alert(payload)
        LOGGER.info("TradingView alert queued for Telegram processing")
        return {"status": "accepted"}

    return app


__all__ = ["create_app"]
