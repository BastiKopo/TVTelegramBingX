"""Translate abstract trade actions into BingX order parameters."""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["OrderMapping", "map_action"]


@dataclass(frozen=True)
class OrderMapping:
    side: str
    position_side: str
    reduce_only: bool


_HEDGE_TABLE = {
    "LONG_OPEN": OrderMapping("BUY", "LONG", False),
    "LONG_CLOSE": OrderMapping("SELL", "LONG", True),
    "SHORT_OPEN": OrderMapping("SELL", "SHORT", False),
    "SHORT_CLOSE": OrderMapping("BUY", "SHORT", True),
}

_ONEWAY_TABLE = {
    "LONG_OPEN": OrderMapping("BUY", "BOTH", False),
    "LONG_CLOSE": OrderMapping("SELL", "BOTH", True),
    "SHORT_OPEN": OrderMapping("SELL", "BOTH", False),
    "SHORT_CLOSE": OrderMapping("BUY", "BOTH", True),
}


def map_action(action: str, *, position_mode: str = "hedge") -> OrderMapping:
    """Return the concrete order parameters for *action* and *position_mode*."""

    token = (action or "").strip().upper()
    if token not in _HEDGE_TABLE:
        raise ValueError(f"Unbekannte Aktion: {action!r}")

    mode = position_mode.strip().lower()
    table = _HEDGE_TABLE if mode != "oneway" else _ONEWAY_TABLE
    return table[token]
