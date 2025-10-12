"""FastAPI webhook endpoint receiving TradingView alerts."""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Final

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from tvtelegrambingx.bot.telegram_bot import handle_signal

LOGGER: Final = logging.getLogger(__name__)

_SECRET_ENV: Final = "TRADINGVIEW_WEBHOOK_SECRET"
_DEFAULT_SECRET: Final = "12345689"

app = FastAPI()


def _resolve_secret() -> str:
    """Return the shared secret expected from TradingView."""

    return os.getenv(_SECRET_ENV, _DEFAULT_SECRET)


@app.post("/tradingview-webhook")
async def tradingview_webhook(request: Request) -> JSONResponse:
    """Receive TradingView alerts, validate the secret and forward to Telegram."""

    body: dict[str, Any] = await request.json()
    secret = body.get("secret")
    if secret != _resolve_secret():
        LOGGER.warning("Unauthorized webhook call rejected")
        return JSONResponse({"status": "unauthorized"}, status_code=401)

    payload = {
        "symbol": body.get("symbol"),
        "action": body.get("action"),
        "timestamp": int(time.time()),
    }

    await handle_signal(payload)
    return JSONResponse({"status": "ok"})


__all__ = ["app", "tradingview_webhook"]
