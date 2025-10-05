"""Repository helpers for position records."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..schemas import Position, PositionStatus, TradeAction


class PositionRepository:
    """CRUD helpers for :class:`Position` instances."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, position: Position) -> Position:
        self._session.add(position)
        await self._session.commit()
        await self._session.refresh(position)
        return position

    async def list_open_for_user(self, user_id: int) -> list[Position]:
        statement = select(Position).where(
            Position.user_id == user_id,
            Position.status == PositionStatus.OPEN,
        )
        result = await self._session.execute(statement)
        return list(result.scalars().all())

    async def get_open_by_symbol(self, symbol: str) -> Position | None:
        statement = select(Position).where(
            Position.symbol == symbol,
            Position.status == PositionStatus.OPEN,
        )
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()

    async def close_position(
        self,
        position: Position,
        *,
        status: PositionStatus = PositionStatus.CLOSED,
        closed_at: datetime | None = None,
    ) -> Position:
        position.status = status
        position.closed_at = closed_at or datetime.now(timezone.utc)
        await self._session.commit()
        await self._session.refresh(position)
        return position

    async def upsert_from_exchange(
        self,
        *,
        symbol: str,
        side: TradeAction,
        quantity: float,
        entry_price: float,
        leverage: int,
    ) -> None:
        position = await self.get_open_by_symbol(symbol)
        if position is None:
            return
        position.action = side
        position.quantity = quantity
        position.entry_price = entry_price
        position.leverage = leverage or position.leverage
        await self._session.commit()
        await self._session.refresh(position)

    async def close_remote_position(self, symbol: str | None) -> None:
        if not symbol:
            return
        position = await self.get_open_by_symbol(symbol)
        if position is None:
            return
        await self.close_position(position)


__all__ = ["PositionRepository"]
