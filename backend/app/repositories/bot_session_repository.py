"""Repository utilities for bot session records."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..schemas import BotSession, BotSessionStatus


class BotSessionRepository:
    """Persist and query :class:`BotSession` entities."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_active_session(self, user_id: int, name: str) -> BotSession | None:
        statement = select(BotSession).where(
            BotSession.user_id == user_id,
            BotSession.name == name,
            BotSession.status == BotSessionStatus.ACTIVE,
        )
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()

    async def get_or_create_active_session(self, user_id: int, name: str) -> BotSession:
        existing = await self.get_active_session(user_id, name)
        if existing is not None:
            return existing

        session = BotSession(user_id=user_id, name=name, status=BotSessionStatus.ACTIVE)
        self._session.add(session)
        await self._session.commit()
        await self._session.refresh(session)
        return session

    async def save_context(self, session: BotSession, context: dict) -> BotSession:
        """Persist updated context information for a session."""

        session.context = context
        await self._session.commit()
        await self._session.refresh(session)
        return session

    async def mark_completed(self, session: BotSession, status: BotSessionStatus = BotSessionStatus.COMPLETED) -> BotSession:
        session.status = status
        session.ended_at = datetime.now(timezone.utc)
        await self._session.commit()
        await self._session.refresh(session)
        return session


__all__ = ["BotSessionRepository"]
