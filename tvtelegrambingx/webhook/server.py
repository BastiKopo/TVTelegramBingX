from __future__ import annotations

import os
import time

from json import JSONDecodeError

from typing import Iterable, List

from fastapi import FastAPI, HTTPException, Request

from tvtelegrambingx.bot.telegram_bot import handle_signal

app = FastAPI()
SECRET = os.getenv("WEBHOOK_SECRET", "12345689")
_PREF_FIELDS = (
    "sl_move_percent",
    "tp_move_percent",
    "tp_move_atr",
    "tp_sell_percent",
    "tp2_move_percent",
    "tp2_move_atr",
    "tp2_sell_percent",
    "tp3_move_percent",
    "tp3_move_atr",
    "tp3_sell_percent",
    "tp4_move_percent",
    "tp4_move_atr",
    "tp4_sell_percent",
)
_ORDER_LEVEL_FIELDS = (
    "sl",
    "stop_loss",
    "stop_loss_price",
    "tp",
    "tp1",
    "take_profit",
    "take_profit_price",
)


@app.get("/health")
async def health():
    return {"ok": True}


def _dedupe_preserve_order(actions: Iterable[str]) -> List[str]:
    """Return a list with duplicates removed while preserving order."""

    return list(dict.fromkeys(actions))


def _iter_actions(raw: object) -> List[str]:
    """Yield normalised action strings from TradingView payload values."""

    actions: List[str] = []

    if raw is None:
        return actions

    if isinstance(raw, str):
        candidates = raw.replace(";", ",").replace("|", ",").replace("\n", ",")
        parts = candidates.split(",") if "," in candidates else [raw]

        for part in parts:
            trimmed = part.strip()
            if not trimmed:
                continue

            # If no explicit separator was present, try whitespace splitting.
            if len(parts) == 1 and " " in trimmed:
                segments = [segment.strip() for segment in trimmed.split() if segment.strip()]
                if len(segments) > 1:
                    actions.extend(segment.upper() for segment in segments)
                    continue

            actions.append(trimmed.upper())

        return _dedupe_preserve_order(actions)

    if isinstance(raw, (list, tuple, set)):
        for entry in raw:
            actions.extend(_iter_actions(entry))
        return _dedupe_preserve_order(actions)

    text = str(raw).strip()
    if text:
        actions.append(text.upper())

    return _dedupe_preserve_order(actions)


@app.post("/tradingview-webhook")
async def tradingview_webhook(req: Request):
    try:
        body = await req.json()
    except JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON payload") from exc
    if body.get("secret") != SECRET:
        return {"status": "unauthorized"}
    raw_actions = body.get("actions")
    if raw_actions is None:
        raw_actions = body.get("action")

    actions = list(_iter_actions(raw_actions))
    payload = {
        "symbol": body.get("symbol"),
        "actions": actions,
        "timestamp": int(time.time()),
    }
    for field in _PREF_FIELDS:
        if field in body:
            payload[field] = body.get(field)
    for field in _ORDER_LEVEL_FIELDS:
        if field in body:
            payload[field] = body.get(field)
    if actions:
        payload["action"] = actions[0]
    await handle_signal(payload)
    return {"status": "ok"}
