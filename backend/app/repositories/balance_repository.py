"""Repository helpers for balance entities."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..schemas import Balance


class BalanceRepository:
    """Manage persistence of :class:`Balance` records."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, user_id: int, asset: str) -> Balance | None:
        statement = select(Balance).where(Balance.user_id == user_id, Balance.asset == asset)
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()

    async def upsert(self, user_id: int, asset: str, *, free: float, locked: float = 0.0) -> Balance:
        balance = await self.get(user_id, asset)
        if balance is None:
            balance = Balance(user_id=user_id, asset=asset, free=free, locked=locked)
            self._session.add(balance)
            await self._session.commit()
            await self._session.refresh(balance)
            return balance

        balance.free = free
        balance.locked = locked
        balance.updated_at = datetime.now(timezone.utc)
        await self._session.commit()
        await self._session.refresh(balance)
        return balance


__all__ = ["BalanceRepository"]
