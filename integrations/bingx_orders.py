"""Lightweight wrapper around :mod:`integrations.bingx_client` order APIs."""

from __future__ import annotations

from typing import Any, Mapping

__all__ = ["post_order"]


async def post_order(params: Mapping[str, Any]) -> Any:
    from webhook import dispatcher

    client = dispatcher.client
    if client is None:
        raise RuntimeError("BingX client ist nicht konfiguriert.")

    quantity_token = params.get("quantity")
    try:
        quantity_value = float(quantity_token)
    except (TypeError, ValueError):
        raise ValueError(f"Ungültige Positionsgröße: {quantity_token!r}")

    position_side_token = params.get("positionSide")
    position_side_value = str(position_side_token).upper() if position_side_token else None

    return await client.place_order(
        symbol=str(params.get("symbol") or ""),
        side=str(params.get("side") or "").upper(),
        position_side=position_side_value,
        quantity=quantity_value,
        order_type=str(params.get("type") or "MARKET").upper(),
        client_order_id=params.get("clientOrderId"),
    )
