"""Repository helpers for order persistence."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..schemas import Order, OrderStatus, TradeAction


class OrderRepository:
    """Provide CRUD helpers for :class:`Order` entities."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, order: Order) -> Order:
        self._session.add(order)
        await self._session.commit()
        await self._session.refresh(order)
        return order

    async def list_for_signal(self, signal_id: int) -> Sequence[Order]:
        statement = select(Order).where(Order.signal_id == signal_id)
        result = await self._session.execute(statement)
        return result.scalars().all()

    async def get(self, order_id: int) -> Order | None:
        statement = select(Order).where(Order.id == order_id)
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()

    async def get_by_exchange_order_id(self, exchange_order_id: str) -> Order | None:
        statement = select(Order).where(Order.exchange_order_id == exchange_order_id)
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()

    async def update_status(
        self,
        order: Order,
        status: OrderStatus,
        *,
        price: float | None = None,
        exchange_order_id: str | None = None,
    ) -> Order:
        order.status = status
        if price is not None:
            order.price = price
        if exchange_order_id is not None:
            order.exchange_order_id = exchange_order_id
        order.updated_at = datetime.now(timezone.utc)
        await self._session.commit()
        await self._session.refresh(order)
        return order

    async def upsert_from_exchange(
        self,
        *,
        symbol: str,
        exchange_order_id: str,
        status: OrderStatus,
        side: TradeAction,
        price: float,
        quantity: float,
    ) -> None:
        existing = await self.get_by_exchange_order_id(exchange_order_id)
        if existing is None:
            return
        existing.symbol = symbol
        existing.status = status
        existing.price = price or existing.price
        existing.quantity = quantity or existing.quantity
        existing.action = side
        existing.updated_at = datetime.now(timezone.utc)
        await self._session.commit()
        await self._session.refresh(existing)


__all__ = ["OrderRepository"]
