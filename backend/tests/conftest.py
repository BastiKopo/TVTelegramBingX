from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from types import SimpleNamespace
from urllib.parse import quote_plus

import pytest
from httpx import ASGITransport, AsyncClient
from pytest_postgresql import factories
from pytest_postgresql.janitor import DatabaseJanitor
from sqlmodel import SQLModel

from backend.app import config
from backend.app.db import get_session_factory, init_engine

postgresql_proc = factories.postgresql_proc()


@pytest.fixture(scope="session")
def event_loop() -> AsyncGenerator[asyncio.AbstractEventLoop, None]:
    loop = asyncio.new_event_loop()
    try:
        yield loop
    finally:
        loop.close()


@pytest.fixture(scope="session")
def postgres_db(postgresql_proc) -> AsyncGenerator[SimpleNamespace, None]:
    dbname = "tvtelegram_backend_test"
    janitor = DatabaseJanitor(
        postgresql_proc.user,
        postgresql_proc.host,
        postgresql_proc.port,
        dbname,
        postgresql_proc.password,
        postgresql_proc.version,
    )
    janitor.init()
    try:
        yield SimpleNamespace(
            user=postgresql_proc.user,
            host=postgresql_proc.host,
            port=postgresql_proc.port,
            password=postgresql_proc.password,
            dbname=dbname,
        )
    finally:
        janitor.drop()


@pytest.fixture(autouse=True)
def _configure_settings(monkeypatch: pytest.MonkeyPatch, postgres_db: SimpleNamespace) -> None:
    password = postgres_db.password or ""
    user = quote_plus(postgres_db.user)
    password_encoded = quote_plus(password)
    if password:
        credentials = f"{user}:{password_encoded}"
    else:
        credentials = user
    database_url = (
        f"postgresql+asyncpg://{credentials}@{postgres_db.host}:{postgres_db.port}/{postgres_db.dbname}"
    )
    monkeypatch.setenv("TRADINGVIEW_WEBHOOK_TOKEN", "test-token")
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("DATABASE_HOST", postgres_db.host)
    monkeypatch.setenv("DATABASE_PORT", str(postgres_db.port))
    monkeypatch.setenv("DATABASE_USER", postgres_db.user)
    monkeypatch.setenv("DATABASE_PASSWORD", password)
    monkeypatch.setenv("DATABASE_NAME", postgres_db.dbname)
    monkeypatch.setenv("DEFAULT_MARGIN_MODE", "cross")
    monkeypatch.setenv("DEFAULT_LEVERAGE", "7")
    monkeypatch.setenv("TRADING_DEFAULT_USERNAME", "test-bot")
    monkeypatch.setenv("TRADING_DEFAULT_SESSION", "integration")
    config.get_settings.cache_clear()


@pytest.fixture
async def setup_database() -> AsyncGenerator[None, None]:
    settings = config.get_settings()
    engine = await init_engine(settings)
    async with engine.begin() as connection:
        await connection.run_sync(SQLModel.metadata.drop_all)
        await connection.run_sync(SQLModel.metadata.create_all)
    try:
        yield
    finally:
        async with engine.begin() as connection:
            await connection.run_sync(SQLModel.metadata.drop_all)


@pytest.fixture
async def client(setup_database) -> AsyncGenerator[AsyncClient, None]:
    from backend.app.main import app

    transport = ASGITransport(app=app, lifespan="on")
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
async def signal_queue(client: AsyncClient) -> asyncio.Queue:
    from backend.app.main import app

    return app.state.signal_queue


@pytest.fixture
async def session_factory(setup_database):
    settings = config.get_settings()
    return get_session_factory(settings)
