"""Helpers for normalising signal actions."""
from __future__ import annotations


SIDE_MAP_KEYS = {
    "LONG_OPEN",
    "LONG_BUY",
    "LONG_CLOSE",
    "LONG_SELL",
    "SHORT_OPEN",
    "SHORT_SELL",
    "SHORT_CLOSE",
    "SHORT_BUY",
}

OPEN_ACTIONS = {"LONG_OPEN", "LONG_BUY", "SHORT_OPEN", "SHORT_SELL"}
CLOSE_ACTIONS = {"LONG_CLOSE", "LONG_SELL", "SHORT_CLOSE", "SHORT_BUY"}


def canonical_action(action: str | None) -> str | None:
    """Return a canonical action identifier understood by BingX clients."""

    if not action:
        return None

    normalized = str(action).upper().replace("-", "_").replace("/", "_")
    normalized = "_".join(part for part in normalized.split("_") if part)

    if normalized in SIDE_MAP_KEYS:
        return normalized

    if "SHORT" in normalized and "BUY" in normalized:
        return "SHORT_BUY"
    if "SHORT" in normalized and "SELL" in normalized:
        return "SHORT_SELL"
    if "SHORT" in normalized and "CLOSE" in normalized:
        return "SHORT_BUY"
    if "LONG" in normalized and "SELL" in normalized:
        return "LONG_SELL"
    if "LONG" in normalized and "BUY" in normalized:
        return "LONG_BUY"
    if "LONG" in normalized and "CLOSE" in normalized:
        return "LONG_SELL"

    if normalized in {"LONG", "BUY"}:
        return "LONG_BUY"
    if normalized in {"SHORT", "SELL"}:
        return "SHORT_SELL"

    return None
