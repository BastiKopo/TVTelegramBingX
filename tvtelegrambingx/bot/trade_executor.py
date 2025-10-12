"""Execute trade actions by forwarding orders to BingX."""

from __future__ import annotations

import logging
from typing import Final

from tvtelegrambingx.integrations.bingx_client import place_order

LOGGER: Final = logging.getLogger(__name__)

_ACTION_MAP: Final = {
    "LONG_BUY": ("BUY", "LONG"),
    "LONG_SELL": ("SELL", "LONG"),
    "SHORT_SELL": ("SELL", "SHORT"),
    "SHORT_BUY": ("BUY", "SHORT"),
}


async def execute_trade(symbol: str, action: str) -> None:
    """Execute the provided *action* for *symbol* through the BingX client."""

    mapping = _ACTION_MAP.get(action)
    if mapping is None:
        LOGGER.warning("Unbekannte Aktion empfangen: %s", action)
        return

    side, position_side = mapping
    LOGGER.info("[TRADE] %s %s %s", symbol, side, position_side)

    try:
        await place_order(symbol, side, position_side)
    except Exception:  # pragma: no cover - errors are logged for observability
        LOGGER.exception("[ERROR] Trade fehlgeschlagen für %s", symbol)


__all__ = ["execute_trade"]
