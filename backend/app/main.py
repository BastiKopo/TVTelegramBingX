"""FastAPI application entrypoint for the TradingView webhook backend."""
from __future__ import annotations

import asyncio
from typing import AsyncGenerator

from fastapi import (
    APIRouter,
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Request,
    Response,
    status,
)
from fastapi.middleware.httpsredirect import HTTPSRedirectMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from .config import Settings, get_settings
from .db import get_session, init_engine
from .integrations.bingx import BingXRESTClient
from .integrations.telegram import (
    InMemorySignalNotifier,
    SignalNotifier,
    TelegramNotifier,
)
from .repositories.balance_repository import BalanceRepository
from .repositories.bot_session_repository import BotSessionRepository
from .repositories.order_repository import OrderRepository
from .repositories.position_repository import PositionRepository
from .repositories.signal_repository import SignalRepository
from .repositories.user_repository import UserRepository
from .schemas import BotState, BotSettingsUpdate, SignalRead, TradingViewSignal
from .services.bingx_account_service import BingXAccountService
from .services.bot_control_service import BotControlService
from .services.signal_service import (
    BrokerPublisher,
    InMemoryPublisher,
    SignalPublisher,
    SignalService,
)
from .metrics import bind_signal_queue_depth
from .telemetry import configure_backend_telemetry

try:  # pragma: no cover - optional dependency
    from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
except Exception:  # pragma: no cover - dependency missing
    CONTENT_TYPE_LATEST = None  # type: ignore
    generate_latest = None  # type: ignore

app = FastAPI(title="TVTelegramBingX Backend", version="0.1.0")
bot_router = APIRouter(prefix="/bot", tags=["bot"])

_app_settings = get_settings()

if _app_settings.force_https:
    app.add_middleware(HTTPSRedirectMiddleware)

if _app_settings.allowed_hosts and _app_settings.allowed_hosts != ["*"]:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=_app_settings.allowed_hosts)

configure_backend_telemetry(app, settings=_app_settings)


@app.on_event("startup")
async def on_startup() -> None:
    settings = get_settings()
    await init_engine(settings)
    app.state.signal_queue = asyncio.Queue()
    bind_signal_queue_depth(app.state.signal_queue.qsize)
    if settings.broker_host:
        broker_publisher = BrokerPublisher(settings)
        await broker_publisher.initialize()
        app.state.publisher = broker_publisher
    else:
        app.state.publisher = InMemoryPublisher(queue=app.state.signal_queue)

    if settings.telegram_bot_token and settings.telegram_chat_id:
        app.state.notifier = TelegramNotifier(
            settings.telegram_bot_token,
            settings.telegram_chat_id,
        )
    else:
        app.state.notifier = InMemorySignalNotifier()


@app.on_event("shutdown")
async def on_shutdown() -> None:
    publisher = getattr(app.state, "publisher", None)
    close = getattr(publisher, "close", None)
    if callable(close):
        await close()

    notifier = getattr(app.state, "notifier", None)
    notifier_close = getattr(notifier, "close", None)
    if callable(notifier_close):
        await notifier_close()


async def get_db_session(settings: Settings = Depends(get_settings)) -> AsyncGenerator:
    async for session in get_session(settings):
        yield session


def get_publisher(request: Request) -> SignalPublisher:
    return request.app.state.publisher


def get_notifier(request: Request) -> SignalNotifier | None:
    return getattr(request.app.state, "notifier", None)


async def get_bingx_client(settings: Settings = Depends(get_settings)) -> AsyncGenerator[BingXRESTClient | None, None]:
    if not settings.bingx_api_key or not settings.bingx_api_secret:
        yield None
        return
    client = BingXRESTClient(
        settings.bingx_api_key,
        settings.bingx_api_secret,
        subaccount_id=settings.bingx_subaccount_id,
    )
    try:
        yield client
    finally:
        await client.close()


async def get_signal_service(
    session: AsyncSession = Depends(get_db_session),
    publisher: SignalPublisher = Depends(get_publisher),
    notifier: SignalNotifier | None = Depends(get_notifier),
    settings: Settings = Depends(get_settings),
) -> SignalService:
    signal_repository = SignalRepository(session)
    order_repository = OrderRepository(session)
    user_repository = UserRepository(session)
    bot_session_repository = BotSessionRepository(session)
    return SignalService(
        signal_repository,
        order_repository,
        user_repository,
        bot_session_repository,
        publisher,
        notifier,
        settings,
    )


async def get_bot_control_service(
    session: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
    client: BingXRESTClient | None = Depends(get_bingx_client),
) -> BotControlService:
    signal_repository = SignalRepository(session)
    user_repository = UserRepository(session)
    bot_session_repository = BotSessionRepository(session)
    balance_repository = BalanceRepository(session)
    position_repository = PositionRepository(session)
    order_repository = OrderRepository(session)
    account_service = (
        BingXAccountService(client, settings)
        if client is not None
        else None
    )
    return BotControlService(
        signal_repository,
        user_repository,
        bot_session_repository,
        balance_repository,
        position_repository,
        settings,
        order_repository=order_repository,
        bingx_account=account_service,
    )


@app.get("/health")
async def healthcheck() -> JSONResponse:
    return JSONResponse({"status": "ok"})


@app.get("/metrics")
async def prometheus_metrics() -> Response:
    if generate_latest is None or CONTENT_TYPE_LATEST is None:  # pragma: no cover - dependency missing
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="prometheus-client is not installed",
        )
    payload = generate_latest()
    return Response(content=payload, media_type=CONTENT_TYPE_LATEST)


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
async def list_signals(
    limit: int = 50,
    signal_service: SignalService = Depends(get_signal_service),
) -> list[SignalRead]:
    signals = await signal_service.list_recent(limit)
    return [SignalRead.model_validate(signal) for signal in signals]


@bot_router.get("/status", response_model=BotState)
async def get_bot_status(service: BotControlService = Depends(get_bot_control_service)) -> BotState:
    state = await service.get_state()
    return BotState.model_validate(state)


@bot_router.post("/settings", response_model=BotState)
async def update_bot_settings(
    payload: BotSettingsUpdate,
    service: BotControlService = Depends(get_bot_control_service),
) -> BotState:
    state = await service.update_state(payload)
    return BotState.model_validate(state)


@bot_router.get("/reports", response_model=list[SignalRead])
async def get_bot_reports(
    limit: int = 5,
    service: BotControlService = Depends(get_bot_control_service),
) -> list[SignalRead]:
    signals = await service.recent_signals(limit)
    return [SignalRead.model_validate(signal) for signal in signals]


app.include_router(bot_router)


__all__ = ["app"]
