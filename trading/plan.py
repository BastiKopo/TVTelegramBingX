"""Resolve effective trading parameters based on Telegram preferences."""

from __future__ import annotations

from typing import Any, Mapping

from bot.user_prefs import get_global, get_symbol
from utils.symbols import norm_symbol

__all__ = ["resolve_effective"]


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


def resolve_effective(chat_id: int, symbol_raw: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    symbol = norm_symbol(symbol_raw)
    symbol_prefs = get_symbol(chat_id, symbol)
    global_prefs = get_global(chat_id)

    qty = payload.get("qty")
    margin_input = (
        payload.get("margin_usdt")
        or payload.get("margin")
        or payload.get("marginAmount")
        or payload.get("marginValue")
    )
    leverage_input = payload.get("lev") or payload.get("leverage")

    margin_value = _coerce_float(margin_input)
    if margin_value is None:
        margin_value = _coerce_float(symbol_prefs.get("margin_usdt"))
    if margin_value is None:
        margin_value = _coerce_float(global_prefs.get("margin_usdt"))
    if margin_value is None:
        margin_value = 0.0

    leverage_value = _coerce_int(leverage_input)
    if leverage_value is None:
        leverage_value = _coerce_int(symbol_prefs.get("leverage"))
    if leverage_value is None:
        leverage_value = _coerce_int(global_prefs.get("leverage"))
    if leverage_value is None:
        leverage_value = 0

    return {
        "symbol": symbol,
        "qty": qty,
        "margin_usdt": float(margin_value),
        "lev": int(leverage_value),
    }
