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
    "margin_usdt",
    "leverage",
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
    "sl_to_entry_after_tp2",
    "sl_to_entry_tp2",
)
_ORDER_LEVEL_FIELDS = (
    "sl",
    "stop_loss",
    "stop_loss_price",
    "tp",
    "tp1",
    "tp1_move",
    "tp1_sell",
    "tp_sell",
    "take_profit",
    "take_profit_price",
    "tp2",
    "tp2_move",
    "tp2_sell",
    "tp3",
    "tp3_move",
    "tp3_sell",
    "tp4",
    "tp4_move",
    "tp4_sell",
)

_SETTINGS_CONTAINER_FIELDS = (
    "trade_settings",
    "settings",
    "webhook_settings",
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
    settings_sources = [body]
    for key in _SETTINGS_CONTAINER_FIELDS:
        nested = body.get(key)
        if isinstance(nested, dict):
            settings_sources.append(nested)

    payload = {
        "symbol": body.get("symbol"),
        "actions": actions,
        "timestamp": int(time.time()),
    }
    for source in settings_sources:
        for field in _PREF_FIELDS:
            if field in source:
                payload[field] = source.get(field)
        for field in _ORDER_LEVEL_FIELDS:
            if field in source:
                payload[field] = source.get(field)
    if actions:
        payload["action"] = actions[0]
    await handle_signal(payload)
    return {"status": "ok"}
