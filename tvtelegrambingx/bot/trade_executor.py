"""Execute trades on BingX."""
from __future__ import annotations

import logging

from tvtelegrambingx.integrations.bingx_client import place_order

LOGGER = logging.getLogger(__name__)

ACTION_MAP = {
    "LONG_BUY": ("BUY", "LONG"),
    "LONG_SELL": ("SELL", "LONG"),
    "SHORT_SELL": ("SELL", "SHORT"),
    "SHORT_BUY": ("BUY", "SHORT"),
}


async def execute_trade(symbol: str, action: str) -> None:
    """Translate user actions into BingX orders."""
    try:
        side, position_side = ACTION_MAP[action]
    except KeyError:
        LOGGER.warning("Unknown trade action received: %s", action)
        return

    LOGGER.info("Submitting BingX order: symbol=%s side=%s position=%s", symbol, side, position_side)
    try:
        await place_order(symbol=symbol, side=side, position_side=position_side)
    except Exception as exc:  # pragma: no cover - defensive logging only
        LOGGER.exception("Trade execution failed: symbol=%s action=%s", symbol, action)
        raise exc
