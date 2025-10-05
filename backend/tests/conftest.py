from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlmodel import SQLModel

from backend.app import config
from backend.app.db import get_session_factory, init_engine

@pytest.fixture(scope="session")
def event_loop() -> AsyncGenerator[asyncio.AbstractEventLoop, None]:
    loop = asyncio.new_event_loop()
    try:
        yield loop
    finally:
        loop.close()


@pytest.fixture(autouse=True)
def _configure_settings(monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory) -> None:
    database_path = tmp_path_factory.mktemp("db") / "test.db"
    database_url = f"sqlite+aiosqlite:///{database_path}"
    monkeypatch.setenv("TRADINGVIEW_WEBHOOK_TOKEN", "test-token")
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("DATABASE_HOST", "localhost")
    monkeypatch.setenv("DATABASE_PORT", "0")
    monkeypatch.setenv("DATABASE_USER", "sqlite")
    monkeypatch.setenv("DATABASE_PASSWORD", "")
    monkeypatch.setenv("DATABASE_NAME", "test")
    monkeypatch.setenv("DEFAULT_MARGIN_MODE", "cross")
    monkeypatch.setenv("DEFAULT_LEVERAGE", "7")
    monkeypatch.setenv("TRADING_DEFAULT_USERNAME", "test-bot")
    monkeypatch.setenv("TRADING_DEFAULT_SESSION", "integration")
    monkeypatch.setenv("FORCE_HTTPS", "false")
    monkeypatch.setenv("ALLOWED_HOSTS", "*")
    monkeypatch.setenv("TELEMETRY_ENABLED", "false")
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
async def notifier(client: AsyncClient):
    from backend.app.main import app

    return app.state.notifier


@pytest.fixture
async def session_factory(setup_database):
    settings = config.get_settings()
    return get_session_factory(settings)
