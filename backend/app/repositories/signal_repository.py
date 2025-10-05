"""Database access helpers for signals."""
from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..schemas import Signal


class SignalRepository:
    """Encapsulates database interaction for signal entities."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, signal: Signal) -> Signal:
        self._session.add(signal)
        await self._session.commit()
        await self._session.refresh(signal)
        return signal

    async def list_recent(self, limit: int = 50) -> Sequence[Signal]:
        statement = select(Signal).order_by(Signal.timestamp.desc()).limit(limit)
        result = await self._session.execute(statement)
        return result.scalars().all()
