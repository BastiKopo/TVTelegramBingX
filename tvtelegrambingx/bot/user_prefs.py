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


def _key(chat_id: int, symbol: str | None = None) -> str:
    if symbol:
        return f"{chat_id}:{symbol.upper()}"
    return f"{chat_id}:__GLOBAL__"


def get_global(chat_id: int) -> Dict[str, Any]:
    return _load().get(_key(chat_id), {})


def get_effective(chat_id: int, symbol: str) -> Dict[str, Any]:
    data = _load()
    effective = dict(data.get(_key(chat_id), {}))
    effective.update(data.get(_key(chat_id, symbol), {}))
    return effective


def set_global(
    chat_id: int,
    *,
    margin_usdt: float | None = None,
    leverage: int | None = None,
    sl_move_percent: float | None = None,
    tp_move_percent: float | None = None,
    tp_move_atr: float | None = None,
    tp_sell_percent: float | None = None,
    tp2_move_percent: float | None = None,
    tp2_move_atr: float | None = None,
    tp2_sell_percent: float | None = None,
    tp3_move_percent: float | None = None,
    tp3_move_atr: float | None = None,
    tp3_sell_percent: float | None = None,
    tp4_move_percent: float | None = None,
    tp4_move_atr: float | None = None,
    tp4_sell_percent: float | None = None,
    sl_to_entry_after_tp2: bool | None = None,
) -> Dict[str, Any]:
    with _LOCK:
        data = _load()
        key = _key(chat_id)
        current = data.get(key, {})
        current.update(
            _build_updates(
                margin_usdt=margin_usdt,
                leverage=leverage,
                sl_move_percent=sl_move_percent,
                tp_move_percent=tp_move_percent,
                tp_move_atr=tp_move_atr,
                tp_sell_percent=tp_sell_percent,
                tp2_move_percent=tp2_move_percent,
                tp2_move_atr=tp2_move_atr,
                tp2_sell_percent=tp2_sell_percent,
                tp3_move_percent=tp3_move_percent,
                tp3_move_atr=tp3_move_atr,
                tp3_sell_percent=tp3_sell_percent,
                tp4_move_percent=tp4_move_percent,
                tp4_move_atr=tp4_move_atr,
                tp4_sell_percent=tp4_sell_percent,
                sl_to_entry_after_tp2=sl_to_entry_after_tp2,
            )
        )
        data[key] = current
        _save(data)
        return current.copy()


def set_symbol(
    chat_id: int,
    symbol: str,
    *,
    margin_usdt: float | None = None,
    leverage: int | None = None,
    sl_move_percent: float | None = None,
    tp_move_percent: float | None = None,
    tp_move_atr: float | None = None,
    tp_sell_percent: float | None = None,
    tp2_move_percent: float | None = None,
    tp2_move_atr: float | None = None,
    tp2_sell_percent: float | None = None,
    tp3_move_percent: float | None = None,
    tp3_move_atr: float | None = None,
    tp3_sell_percent: float | None = None,
    tp4_move_percent: float | None = None,
    tp4_move_atr: float | None = None,
    tp4_sell_percent: float | None = None,
    sl_to_entry_after_tp2: bool | None = None,
) -> Dict[str, Any]:
    with _LOCK:
        data = _load()
        key = _key(chat_id, symbol)
        current = data.get(key, {})
        current.update(
            _build_updates(
                margin_usdt=margin_usdt,
                leverage=leverage,
                sl_move_percent=sl_move_percent,
                tp_move_percent=tp_move_percent,
                tp_move_atr=tp_move_atr,
                tp_sell_percent=tp_sell_percent,
                tp2_move_percent=tp2_move_percent,
                tp2_move_atr=tp2_move_atr,
                tp2_sell_percent=tp2_sell_percent,
                tp3_move_percent=tp3_move_percent,
                tp3_move_atr=tp3_move_atr,
                tp3_sell_percent=tp3_sell_percent,
                tp4_move_percent=tp4_move_percent,
                tp4_move_atr=tp4_move_atr,
                tp4_sell_percent=tp4_sell_percent,
                sl_to_entry_after_tp2=sl_to_entry_after_tp2,
            )
        )
        data[key] = current
        _save(data)
        return current.copy()


def _build_updates(
    *,
    margin_usdt: float | None = None,
    leverage: int | None = None,
    sl_move_percent: float | None = None,
    tp_move_percent: float | None = None,
    tp_move_atr: float | None = None,
    tp_sell_percent: float | None = None,
    tp2_move_percent: float | None = None,
    tp2_move_atr: float | None = None,
    tp2_sell_percent: float | None = None,
    tp3_move_percent: float | None = None,
    tp3_move_atr: float | None = None,
    tp3_sell_percent: float | None = None,
    tp4_move_percent: float | None = None,
    tp4_move_atr: float | None = None,
    tp4_sell_percent: float | None = None,
    sl_to_entry_after_tp2: bool | None = None,
) -> Dict[str, Any]:
    updates: Dict[str, Any] = {}
    if margin_usdt is not None:
        updates["margin_usdt"] = float(margin_usdt)
    if leverage is not None:
        updates["leverage"] = int(leverage)
    if sl_move_percent is not None:
        updates["sl_move_percent"] = float(sl_move_percent)
    if tp_move_percent is not None:
        updates["tp_move_percent"] = float(tp_move_percent)
    if tp_move_atr is not None:
        updates["tp_move_atr"] = float(tp_move_atr)
    if tp_sell_percent is not None:
        updates["tp_sell_percent"] = float(tp_sell_percent)
    if tp2_move_percent is not None:
        updates["tp2_move_percent"] = float(tp2_move_percent)
    if tp2_move_atr is not None:
        updates["tp2_move_atr"] = float(tp2_move_atr)
    if tp2_sell_percent is not None:
        updates["tp2_sell_percent"] = float(tp2_sell_percent)
    if tp3_move_percent is not None:
        updates["tp3_move_percent"] = float(tp3_move_percent)
    if tp3_move_atr is not None:
        updates["tp3_move_atr"] = float(tp3_move_atr)
    if tp3_sell_percent is not None:
        updates["tp3_sell_percent"] = float(tp3_sell_percent)
    if tp4_move_percent is not None:
        updates["tp4_move_percent"] = float(tp4_move_percent)
    if tp4_move_atr is not None:
        updates["tp4_move_atr"] = float(tp4_move_atr)
    if tp4_sell_percent is not None:
        updates["tp4_sell_percent"] = float(tp4_sell_percent)
    if sl_to_entry_after_tp2 is not None:
        updates["sl_to_entry_after_tp2"] = bool(sl_to_entry_after_tp2)
    return updates
