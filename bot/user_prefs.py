"""Persist and retrieve Telegram-configured trading preferences."""

from __future__ import annotations

import json
import os
import threading
from typing import Any, Dict

from utils.symbols import norm_symbol

__all__ = [
    "get",
    "get_global",
    "get_prefs",
    "get_symbol",
    "key_glob",
    "key_sym",
    "set_global",
    "set_symbol",
    "set_for_symbol",
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
            handle.write("{}")
            return {}
    with open(_PATH, "r", encoding="utf-8") as handle:
        try:
            data = json.load(handle)
        except json.JSONDecodeError:
            return {}
    return data if isinstance(data, dict) else {}


def _save(data: Dict[str, Any]) -> None:
    _ensure_parent_dir()
    with open(_PATH, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)


def key_sym(chat_id: int | str, sym: str) -> str:
    return f"{chat_id}:{sym}"


def key_glob(chat_id: int | str) -> str:
    return f"{chat_id}:__GLOBAL__"


def get_symbol(chat_id: int | str, symbol: str) -> Dict[str, Any]:
    normalized = norm_symbol(symbol)
    with _LOCK:
        data = _load()
        return dict(data.get(key_sym(chat_id, normalized), {}))


def set_symbol(
    chat_id: int | str,
    symbol: str,
    *,
    margin_usdt: float | None = None,
    leverage: int | None = None,
) -> Dict[str, Any]:
    normalized = norm_symbol(symbol)
    with _LOCK:
        data = _load()
        key = key_sym(chat_id, normalized)
        current = dict(data.get(key, {}))
        if margin_usdt is not None:
            current["margin_usdt"] = float(margin_usdt)
        if leverage is not None:
            current["leverage"] = int(leverage)
        data[key] = current
        _save(data)
        return current


def get_global(chat_id: int | str) -> Dict[str, Any]:
    with _LOCK:
        data = _load()
        return dict(data.get(key_glob(chat_id), {}))


def set_global(
    chat_id: int | str,
    *,
    margin_usdt: float | None = None,
    leverage: int | None = None,
) -> Dict[str, Any]:
    with _LOCK:
        data = _load()
        key = key_glob(chat_id)
        current = dict(data.get(key, {}))
        if margin_usdt is not None:
            current["margin_usdt"] = float(margin_usdt)
        if leverage is not None:
            current["leverage"] = int(leverage)
        data[key] = current
        _save(data)
        return current


def get(chat_id: int | str, symbol: str | None = None) -> Dict[str, Any]:
    if symbol:
        return get_symbol(chat_id, symbol)
    return get_global(chat_id)


def set_for_symbol(
    chat_id: int | str,
    symbol: str,
    *,
    margin_usdt: float | None = None,
    leverage: int | None = None,
) -> Dict[str, Any]:
    return set_symbol(chat_id, symbol, margin_usdt=margin_usdt, leverage=leverage)


def _coerce_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        if isinstance(value, str) and not value.strip():
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _coerce_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        if isinstance(value, str) and not value.strip():
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def get_prefs(
    chat_id: int | str,
    symbol: str,
    *,
    state: Any | None = None,  # kept for backwards compatibility with callers
) -> dict[str, Any]:
    symbol_token = norm_symbol(symbol)
    symbol_data = get_symbol(chat_id, symbol_token)
    global_data = get_global(chat_id)

    margin_value = _coerce_float(symbol_data.get("margin_usdt"))
    if margin_value is None:
        margin_value = _coerce_float(global_data.get("margin_usdt"))
    if margin_value is None:
        margin_value = 0.0

    leverage_value = _coerce_int(symbol_data.get("leverage"))
    if leverage_value is None:
        leverage_value = _coerce_int(global_data.get("leverage"))
    if leverage_value is None:
        leverage_value = 0

    return {
        "margin_usdt": float(margin_value),
        "leverage": int(leverage_value),
        "lev_long": int(leverage_value),
        "lev_short": int(leverage_value),
    }
