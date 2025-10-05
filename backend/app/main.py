"""FastAPI application entrypoint for the TradingView webhook backend."""
from __future__ import annotations

import asyncio
from typing import AsyncGenerator

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from .config import Settings, get_settings
from .db import get_session, init_engine
from .repositories.signal_repository import SignalRepository
from .schemas import SignalRead, TradingViewSignal
from .services.signal_service import InMemoryPublisher, SignalService

app = FastAPI(title="TVTelegramBingX Backend", version="0.1.0")


@app.on_event("startup")
async def on_startup() -> None:
    settings = get_settings()
    await init_engine(settings)
    app.state.signal_queue = asyncio.Queue()
    app.state.publisher = InMemoryPublisher(queue=app.state.signal_queue)


async def get_db_session(settings: Settings = Depends(get_settings)) -> AsyncGenerator:
    async for session in get_session(settings):
        yield session


def get_publisher(request: Request) -> InMemoryPublisher:
    return request.app.state.publisher


async def get_signal_service(
    session: AsyncSession = Depends(get_db_session),
    publisher: InMemoryPublisher = Depends(get_publisher),
    settings: Settings = Depends(get_settings),
) -> SignalService:
    repository = SignalRepository(session)
    return SignalService(repository, publisher, settings)


@app.get("/health")
async def healthcheck() -> JSONResponse:
    return JSONResponse({"status": "ok"})


@app.post("/webhook/tradingview", response_model=SignalRead, status_code=status.HTTP_201_CREATED)
async def tradingview_webhook(
    payload: TradingViewSignal,
    signal_service: SignalService = Depends(get_signal_service),
    token: str = Header(..., alias="X-TRADINGVIEW-TOKEN"),
    settings: Settings = Depends(get_settings),
) -> SignalRead:
    if token != settings.tradingview_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid webhook token")

    stored_signal = await signal_service.ingest(payload)
    return SignalRead.model_validate(stored_signal)


@app.get("/signals", response_model=list[SignalRead])
async def list_signals(signal_service: SignalService = Depends(get_signal_service)) -> list[SignalRead]:
    signals = await signal_service.list_recent()
    return [SignalRead.model_validate(signal) for signal in signals]


__all__ = ["app"]
