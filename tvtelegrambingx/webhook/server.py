"""FastAPI server receiving TradingView alerts."""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict

from fastapi import FastAPI, HTTPException, Request

from tvtelegrambingx.bot.telegram_bot import handle_signal
from tvtelegrambingx.config import Settings
from tvtelegrambingx.config_store import ConfigStore
from tvtelegrambingx.logic_button import place_market_like_button

LOGGER = logging.getLogger(__name__)
CONFIG_STORE = ConfigStore()


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

        payload: Dict[str, Any] = {
            "symbol": symbol,
            "action": action,
            "timestamp": int(time.time()),
            "order_type": body.get("order_type") or "MARKET",
            "executed": True,
        }

        try:
            effective_cfg = CONFIG_STORE.get_effective(symbol)
            result = await place_market_like_button(signal=payload, eff_cfg=effective_cfg)
        except Exception as exc:
            LOGGER.exception("Failed to execute button-mode order for %s", symbol)
            raise HTTPException(status_code=400, detail=f"Trade fehlgeschlagen: {exc}") from exc

        payload["quantity"] = result.get("quantity")
        await handle_signal(payload)
        exchange_result = json.dumps(result.get("order"), ensure_ascii=False)
        quantity_value = result.get("quantity")
        quantity_str = "" if quantity_value is None else str(quantity_value)
        return {"status": "ok", "exchange_result": exchange_result, "quantity": quantity_str}

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
