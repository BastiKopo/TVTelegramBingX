"""Repository helpers for user persistence."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..schemas import User


class UserRepository:
    """Encapsulates database access for :class:`User` entities."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_username(self, username: str) -> User | None:
        statement = select(User).where(User.username == username)
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()

    async def create(self, user: User) -> User:
        self._session.add(user)
        await self._session.commit()
        await self._session.refresh(user)
        return user

    async def get_or_create_by_username(self, username: str, *, is_active: bool = True) -> User:
        existing = await self.get_by_username(username)
        if existing is not None:
            return existing

        user = User(username=username, is_active=is_active)
        self._session.add(user)
        try:
            await self._session.commit()
        except IntegrityError:
            await self._session.rollback()
            statement = select(User).where(User.username == username)
            result = await self._session.execute(statement)
            user = result.scalar_one()
        else:
            await self._session.refresh(user)
        return user


__all__ = ["UserRepository"]
