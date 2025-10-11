"""Helpers for persisting Telegram-configured trading preferences."""

from __future__ import annotations

import json
import os
import threading
from typing import Any, Dict

from bot.state import BotState
from utils.symbols import norm_symbol

__all__ = [
    "get",
    "set_for_symbol",
    "set_global",
    "get_prefs",
]

_LOCK = threading.Lock()
_PATH = os.getenv("USER_PREFS_PATH", "./data/user_prefs.json")


def _ensure_parent_dir() -> None:
    directory = os.path.dirname(_PATH) or "."
    os.makedirs(directory, exist_ok=True)


def _load() -> Dict[str, Any]:
    _ensure_parent_dir()
    if not os.path.exists(_PATH):
        with open(_PATH, "w", encoding="utf-8") as handle:
            json.dump({}, handle)
        return {}

    try:
        with open(_PATH, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (json.JSONDecodeError, OSError):
        data = {}
    if not isinstance(data, dict):
        return {}
    return data


def _save(data: Dict[str, Any]) -> None:
    _ensure_parent_dir()
    with open(_PATH, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2, sort_keys=True)


def _key(chat_id: int | str, symbol: str) -> str:
    return f"{chat_id}:{symbol}"


def get(chat_id: int | str, symbol: str | None = None) -> Dict[str, Any]:
    """Return stored preferences for ``chat_id``.

    When *symbol* is provided symbol-specific overrides are returned, otherwise
    the global defaults for the chat are retrieved.  The helper never raises and
    falls back to an empty mapping when no data was previously stored.
    """

    with _LOCK:
        payload = _load()
        if symbol:
            return payload.get(_key(chat_id, norm_symbol(symbol)), {})
        return payload.get(f"{chat_id}:__GLOBAL__", {})


def set_for_symbol(
    chat_id: int | str,
    symbol: str,
    *,
    margin_usdt: float | None = None,
    leverage: int | None = None,
) -> Dict[str, Any]:
    """Persist overrides for ``symbol`` in ``chat_id``."""

    normalized = norm_symbol(symbol)

    with _LOCK:
        payload = _load()
        key = _key(chat_id, normalized)
        current = dict(payload.get(key) or {})
        if margin_usdt is not None:
            current["margin_usdt"] = float(margin_usdt)
        if leverage is not None:
            current["leverage"] = int(leverage)
        payload[key] = current
        _save(payload)
        return current


def set_global(
    chat_id: int | str,
    *,
    margin_usdt: float | None = None,
    leverage: int | None = None,
    isolated: bool | None = None,
    hedge: bool | None = None,
    tif: str | None = None,
) -> Dict[str, Any]:
    """Persist global defaults for ``chat_id``."""

    with _LOCK:
        payload = _load()
        key = f"{chat_id}:__GLOBAL__"
        current = dict(payload.get(key) or {})
        if margin_usdt is not None:
            current["margin_usdt"] = float(margin_usdt)
        if leverage is not None:
            current["leverage"] = int(leverage)
        if isolated is not None:
            current["isolated"] = bool(isolated)
        if hedge is not None:
            current["hedge"] = bool(hedge)
        if tif is not None:
            current["tif"] = str(tif)
        payload[key] = current
        _save(payload)
        return current


def _coerce_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _coerce_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def get_prefs(
    chat_id: int | str | None,
    symbol: str,
    *,
    state: BotState | None = None,
) -> dict[str, Any]:
    """Return preferences merged from symbol overrides, global defaults and state."""

    symbol_token = norm_symbol(symbol)
    chat_token = chat_id if chat_id is not None else ""

    symbol_data = get(chat_token, symbol_token)
    global_data = get(chat_token)

    margin = _coerce_float(symbol_data.get("margin_usdt"))
    if margin is None:
        margin = _coerce_float(global_data.get("margin_usdt"))
    if margin is None and isinstance(state, BotState):
        margin = _coerce_float(state.global_trade.margin_usdt)
    margin = float(margin or 0.0)

    leverage = _coerce_int(symbol_data.get("leverage"))
    if leverage is None:
        leverage = _coerce_int(global_data.get("leverage"))
    if leverage is None and isinstance(state, BotState):
        lev_long = _coerce_int(state.global_trade.lev_long)
        lev_short = _coerce_int(state.global_trade.lev_short)
        leverage = lev_long or lev_short
    leverage = int(leverage or 0)

    result: dict[str, Any] = {
        "margin_usdt": margin,
        "lev_long": leverage,
        "lev_short": leverage,
    }
    if leverage > 0:
        result["leverage"] = leverage
    return result
