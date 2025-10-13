"""Helpers to ensure leverage is configured on BingX."""

from __future__ import annotations

from typing import Any, Dict, Optional

from tvtelegrambingx.integrations import bingx_client


def _clamp_leverage(sym_filters: Optional[Dict[str, Any]], leverage: int) -> int:
    """Clamp the leverage based on symbol filters."""

    max_lev: Optional[int] = None
    if sym_filters:
        candidate = (
            sym_filters.get("maxLeverage")
            or sym_filters.get("maxOpenLeverage")
            or sym_filters.get("maxPositionLeverage")
            or sym_filters.get("max_leverage")
        )
        try:
            if candidate is not None:
                max_lev = int(candidate)
        except (TypeError, ValueError):
            max_lev = None

    leverage = int(leverage)
    if leverage < 1:
        leverage = 1
    if max_lev:
        leverage = min(leverage, max_lev)
    else:
        leverage = min(leverage, 125)
    return leverage


async def set_leverage_for_side(symbol: str, leverage: int, position_side: str) -> Dict[str, Any]:
    """Apply the leverage for a specific hedge-mode side."""

    side = position_side.upper()
    if side not in {"LONG", "SHORT"}:
        raise ValueError("positionSide muss LONG oder SHORT sein")

    return await bingx_client.set_leverage(
        symbol=symbol,
        leverage=int(leverage),
        position_side=side,
    )


async def ensure_leverage_both(
    symbol: str,
    leverage: int,
    sym_filters: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Ensure the leverage is applied for LONG and SHORT sides in hedge mode."""

    effective_leverage = _clamp_leverage(sym_filters, leverage)
    long_response = await set_leverage_for_side(symbol, effective_leverage, "LONG")
    short_response = await set_leverage_for_side(symbol, effective_leverage, "SHORT")
    return {
        "leverage": effective_leverage,
        "LONG": long_response,
        "SHORT": short_response,
    }
