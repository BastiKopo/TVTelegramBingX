"""Helpers for resolving effective trade parameters."""

from __future__ import annotations

from typing import Any, Mapping

from bot.state import BotState
from bot.user_prefs import get_prefs
from services.symbols import normalize_symbol

__all__ = ["resolve_effective_trade_params"]


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


def _preferred_leverage(prefs: Mapping[str, Any], action: str) -> int:
    token = (action or "").strip().upper()
    lev_long = int(prefs.get("lev_long") or prefs.get("leverage") or 0)
    lev_short = int(prefs.get("lev_short") or lev_long or prefs.get("leverage") or 0)

    if token.startswith("SHORT"):
        return lev_short or lev_long
    return lev_long or lev_short


def _fallback_state_margin(state: BotState | None) -> float:
    if isinstance(state, BotState):
        try:
            return float(state.global_trade.margin_usdt or 0.0)
        except Exception:  # pragma: no cover - guard against misconfigured state
            return 0.0
    return 0.0


def _fallback_state_leverage(state: BotState | None) -> int:
    if isinstance(state, BotState):
        try:
            lev_long = int(state.global_trade.lev_long or 0)
            lev_short = int(state.global_trade.lev_short or 0)
        except Exception:  # pragma: no cover - guard against misconfigured state
            return 0
        return lev_long or lev_short
    return 0


def resolve_effective_trade_params(
    state: BotState,
    chat_id: int | str | None,
    symbol_raw: str,
    action: str,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Return the effective trade parameters for an order."""

    if not isinstance(state, BotState):
        raise ValueError("Ungültiger Bot-Zustand – bitte /sync ausführen.")

    symbol = normalize_symbol(symbol_raw)
    prefs = get_prefs(chat_id, symbol, state=state)

    quantity = _coerce_float(payload.get("quantity"))
    if quantity is None:
        quantity = _coerce_float(payload.get("qty"))

    margin_usdt = _coerce_float(
        payload.get("margin_usdt")
        or payload.get("margin")
        or payload.get("marginAmount")
        or payload.get("marginValue")
    )

    leverage_override = _coerce_int(
        payload.get("leverage_override")
        or payload.get("lev")
        or payload.get("leverage")
    )

    margin_pref = float(prefs.get("margin_usdt") or 0.0)
    leverage_pref = _preferred_leverage(prefs, action)

    if margin_pref <= 0:
        margin_pref = _fallback_state_margin(state)
    if leverage_pref <= 0:
        leverage_pref = _fallback_state_leverage(state)

    if quantity is not None:
        effective_margin = margin_usdt if margin_usdt is not None else (margin_pref or None)
        effective_leverage = leverage_override if leverage_override is not None else (
            leverage_pref if leverage_pref > 0 else None
        )
        return {
            "symbol": symbol,
            "quantity": quantity,
            "margin_usdt": effective_margin,
            "leverage": effective_leverage,
        }

    effective_margin = margin_usdt if margin_usdt is not None else margin_pref
    effective_leverage = leverage_override if leverage_override is not None else leverage_pref

    if effective_margin <= 0 or effective_leverage <= 0:
        raise ValueError(
            "Bitte zuerst Margin und Leverage in Telegram konfigurieren (/margin, /leverage)."
        )

    return {
        "symbol": symbol,
        "quantity": None,
        "margin_usdt": float(effective_margin),
        "leverage": int(effective_leverage),
    }
