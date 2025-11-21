"""Persist global per-chat trading preferences."""
from __future__ import annotations

import json
import os
import threading
from typing import Any, Dict

_LOCK = threading.Lock()
_PATH = os.getenv("USER_PREFS_PATH", "./data/user_prefs.json")


def _load() -> Dict[str, Any]:
    os.makedirs(os.path.dirname(_PATH) or ".", exist_ok=True)
    if not os.path.exists(_PATH):
        with open(_PATH, "w", encoding="utf-8") as handle:
            handle.write("{}")
    with open(_PATH, "r", encoding="utf-8") as handle:
        try:
            data = json.load(handle)
        except json.JSONDecodeError:
            data = {}
    if not isinstance(data, dict):
        data = {}
    return data


def _save(data: Dict[str, Any]) -> None:
    with open(_PATH, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)


def _key(chat_id: int) -> str:
    return f"{chat_id}:__GLOBAL__"


def get_global(chat_id: int) -> Dict[str, Any]:
    return _load().get(_key(chat_id), {})


def set_global(
    chat_id: int,
    *,
    margin_usdt: float | None = None,
    leverage: int | None = None,
    sl_move_percent: float | None = None,
    tp_move_percent: float | None = None,
    tp_sell_percent: float | None = None,
    tp2_move_percent: float | None = None,
    tp2_sell_percent: float | None = None,
    tp3_move_percent: float | None = None,
    tp3_sell_percent: float | None = None,
) -> Dict[str, Any]:
    with _LOCK:
        data = _load()
        key = _key(chat_id)
        current = data.get(key, {})
        if margin_usdt is not None:
            current["margin_usdt"] = float(margin_usdt)
        if leverage is not None:
            current["leverage"] = int(leverage)
        if sl_move_percent is not None:
            current["sl_move_percent"] = float(sl_move_percent)
        if tp_move_percent is not None:
            current["tp_move_percent"] = float(tp_move_percent)
        if tp_sell_percent is not None:
            current["tp_sell_percent"] = float(tp_sell_percent)
        if tp2_move_percent is not None:
            current["tp2_move_percent"] = float(tp2_move_percent)
        if tp2_sell_percent is not None:
            current["tp2_sell_percent"] = float(tp2_sell_percent)
        if tp3_move_percent is not None:
            current["tp3_move_percent"] = float(tp3_move_percent)
        if tp3_sell_percent is not None:
            current["tp3_sell_percent"] = float(tp3_sell_percent)
        data[key] = current
        _save(data)
        return current.copy()
