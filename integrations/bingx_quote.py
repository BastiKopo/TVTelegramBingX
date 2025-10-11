"""Minimal wrapper for retrieving BingX mark prices."""

from __future__ import annotations

from decimal import Decimal

__all__ = ["get_mark_price"]


async def get_mark_price(symbol: str) -> str:
    from webhook import dispatcher

    client = dispatcher.client
    if client is None:
        raise RuntimeError("BingX client ist nicht konfiguriert.")
    price = await client.get_mark_price(symbol)
    return format(Decimal(str(price)).normalize(), "f")
