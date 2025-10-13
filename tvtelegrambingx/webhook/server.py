from __future__ import annotations

import os
import time

from json import JSONDecodeError

from fastapi import FastAPI, HTTPException, Request

from tvtelegrambingx.bot.telegram_bot import handle_signal

app = FastAPI()
SECRET = os.getenv("WEBHOOK_SECRET", "12345689")


@app.get("/health")
async def health():
    return {"ok": True}


@app.post("/tradingview-webhook")
async def tradingview_webhook(req: Request):
    try:
        body = await req.json()
    except JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON payload") from exc
    if body.get("secret") != SECRET:
        return {"status": "unauthorized"}
    payload = {
        "symbol": body.get("symbol"),
        "action": (body.get("action") or "").upper(),
        "timestamp": int(time.time()),
    }
    await handle_signal(payload)
    return {"status": "ok"}
