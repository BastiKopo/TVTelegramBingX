"""Database utilities."""
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from .config import Settings

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


async def init_engine(settings: Settings) -> AsyncEngine:
    """Initialise the async engine based on provided settings."""

    global _engine, _session_factory
    if _engine is None:
        _engine = create_async_engine(str(settings.database_url), echo=False, future=True)
        _session_factory = async_sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def get_session_factory(settings: Settings) -> async_sessionmaker[AsyncSession]:
    """Return a configured async session factory."""

    if _session_factory is None:
        raise RuntimeError("Database engine not initialised. Call init_engine first.")
    return _session_factory


async def get_session(settings: Settings) -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding an :class:`AsyncSession`."""

    factory = get_session_factory(settings)
    async with factory() as session:
        yield session
