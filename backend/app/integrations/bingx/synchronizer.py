"""Services responsible for reconciling BingX data with local storage."""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from ...repositories.order_repository import OrderRepository
from ...repositories.position_repository import PositionRepository
from ...schemas import OrderStatus, TradeAction
from .rest import BingXRESTClient


class BingXSyncService:
    """Pull order and position data from BingX and persist locally."""

    def __init__(
        self,
        client: BingXRESTClient,
        order_repository: OrderRepository,
        position_repository: PositionRepository,
    ) -> None:
        self._client = client
        self._orders = order_repository
        self._positions = position_repository

    async def resync_orders(self, *, symbol: str | None = None) -> None:
        items: Sequence[dict[str, Any]] = await self._client.get_all_orders(symbol)
        for item in items:
            await self._orders.upsert_from_exchange(
                symbol=item["symbol"],
                exchange_order_id=item["orderId"],
                status=_map_order_status(item.get("status")),
                side=_map_side(item.get("side")),
                price=float(item.get("avgPrice") or item.get("price") or 0.0),
                quantity=float(item.get("origQty") or item.get("quantity") or 0.0),
            )

    async def resync_positions(self, *, symbol: str | None = None) -> None:
        positions = await self._client.get_positions(symbol)
        for payload in positions:
            if float(payload.get("positionAmt", 0)) == 0:
                await self._positions.close_remote_position(payload.get("symbol"))
                continue
            await self._positions.upsert_from_exchange(
                symbol=payload["symbol"],
                side=_map_side(payload.get("positionSide")),
                quantity=float(payload.get("positionAmt")),
                entry_price=float(payload.get("entryPrice", 0.0)),
                leverage=int(payload.get("leverage", 0)),
            )


def _map_side(value: str | None) -> TradeAction:
    return TradeAction.BUY if str(value).lower() in {"buy", "long"} else TradeAction.SELL


def _map_order_status(value: str | None) -> OrderStatus:
    lookup = {
        "new": OrderStatus.SUBMITTED,
        "filled": OrderStatus.FILLED,
        "cancelled": OrderStatus.CANCELLED,
        "canceled": OrderStatus.CANCELLED,
        "rejected": OrderStatus.REJECTED,
        "partially_filled": OrderStatus.SUBMITTED,
    }
    return lookup.get(str(value).lower(), OrderStatus.PENDING)


__all__ = ["BingXSyncService"]
