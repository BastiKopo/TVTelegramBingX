from __future__ import annotations

import os
import time

from fastapi import FastAPI, Request

from tvtelegrambingx.bot.telegram_bot import handle_signal

app = FastAPI()
SECRET = os.getenv("WEBHOOK_SECRET", "12345689")


@app.get("/health")
async def health():
    return {"ok": True}


@app.post("/tradingview-webhook")
async def tradingview_webhook(req: Request):
    body = await req.json()
    if body.get("secret") != SECRET:
        return {"status": "unauthorized"}
    payload = {
        "symbol": body.get("symbol"),
        "action": (body.get("action") or "").upper(),
        "timestamp": int(time.time()),
    }
    await handle_signal(payload)
    return {"status": "ok"}
