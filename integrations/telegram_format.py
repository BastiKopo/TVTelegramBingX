"""Helpers for building Telegram signal messages with a unified layout."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

__all__ = ["build_signal_message"]


def _emoji_and_title(intent: str) -> tuple[str, str]:
    token = (intent or "").upper()
    if token == "LONG_OPEN":
        return "🟢", "Buy"
    if token == "SHORT_OPEN":
        return "🔴", "Sell"
    if token == "LONG_CLOSE":
        return "⚪", "Close Long"
    if token == "SHORT_CLOSE":
        return "⚫", "Close Short"
    return "⚪", "Signal"


def _auto_trade_str(enabled: bool) -> str:
    return "On" if enabled else "Off"


def _timestamp_str(ts: Optional[datetime] = None) -> str:
    ts = ts or datetime.now()
    return ts.strftime("%Y-%m-%d %H:%M:%S")


def _format_number(value: float | int) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    text = f"{number:.10f}".rstrip("0").rstrip(".")
    return text or "0"


def build_signal_message(
    *,
    symbol: str,
    intent: str,
    order_type: str = "Market",
    position_side: str = "LONG",
    auto_trade: bool = False,
    leverage: Optional[float] = None,
    margin_usdt: Optional[float] = None,
    quantity: Optional[str] = None,
    reduce_only: bool = False,
    timestamp: Optional[datetime] = None,
) -> str:
    emoji, title = _emoji_and_title(intent)

    lines = [f"{emoji} SIGNAL - {title}", "-" * 24]

    lines.append(f"Asset: {symbol}")

    if margin_usdt is not None:
        lines.append(f"Margin: {_format_number(margin_usdt)} USDT")
    elif quantity is not None:
        lines.append(f"Quantity: {quantity}")

    if leverage is not None:
        leverage_text = _format_number(leverage)
        lines.append(f"Leverage: {leverage_text}x")

    lines.append(f"Auto-trade: {_auto_trade_str(auto_trade)}")

    normalised_type = order_type or "Market"
    if "CLOSE" in (intent or "").upper():
        exit_text = normalised_type
        if reduce_only:
            exit_text = f"{exit_text} (Reduce Only)"
        lines.append(f"Exit Type: {exit_text}")
    else:
        lines.append(f"Entry Type: {normalised_type}")

    lines.append(f"Position Side: {position_side.upper()}")

    lines.append(f"Timestamp: {_timestamp_str(timestamp)}")

    return "\n".join(lines)
