"""Thin adapter to ensure leverage settings before order placement."""

from __future__ import annotations

__all__ = ["ensure_leverage"]


async def ensure_leverage(symbol: str, lev: int, position_side: str) -> None:
    from webhook import dispatcher

    client = dispatcher.client
    if client is None:
        raise RuntimeError("BingX client ist nicht konfiguriert.")
    await client.set_leverage(symbol=symbol, leverage=lev, positionSide=position_side)
