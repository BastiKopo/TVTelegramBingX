"""FastAPI server receiving TradingView alerts."""
from __future__ import annotations

import logging
import time
from typing import Any, Dict

from fastapi import FastAPI, HTTPException, Request

from tvtelegrambingx.bot.telegram_bot import handle_signal
from tvtelegrambingx.config import Settings

LOGGER = logging.getLogger(__name__)


def build_app(settings: Settings) -> FastAPI:
    app = FastAPI()

    configured_route = settings.tradingview_webhook_route or "/tradingview-webhook"
    if not configured_route.startswith("/"):
        configured_route = f"/{configured_route}"

    webhook_paths = {"/tradingview-webhook", configured_route}

    async def tradingview_webhook(request: Request) -> Dict[str, str]:
        body: Dict[str, Any] = await request.json()
        secret = body.get("secret")
        if settings.tradingview_secret and secret != settings.tradingview_secret:
            LOGGER.warning("Rejected webhook with invalid secret")
            raise HTTPException(status_code=401, detail="unauthorized")

        symbol = body.get("symbol")
        action = body.get("action")
        if not symbol or not action:
            LOGGER.warning("Webhook missing symbol/action: %s", body)
            raise HTTPException(status_code=400, detail="invalid payload")

        payload = {
            "symbol": symbol,
            "action": action,
            "timestamp": int(time.time()),
        }
        await handle_signal(payload)
        return {"status": "ok"}

    for path in sorted(webhook_paths):
        app.add_api_route(
            path,
            tradingview_webhook,
            methods=["POST"],
            name=f"tradingview_webhook_{path.strip('/').replace('/', '_') or 'root'}",
        )

    @app.get("/health")
    async def health() -> Dict[str, str]:
        return {"status": "ok"}

    return app
