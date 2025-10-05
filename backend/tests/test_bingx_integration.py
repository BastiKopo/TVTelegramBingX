from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import httpx
import pytest

from backend.app.config import get_settings
from backend.app.integrations.bingx import BingXRESTClient, BingXRESTError, BingXSyncService, build_signature
from backend.app.repositories.bot_session_repository import BotSessionRepository
from backend.app.repositories.order_repository import OrderRepository
from backend.app.repositories.position_repository import PositionRepository
from backend.app.repositories.signal_repository import SignalRepository
from backend.app.repositories.user_repository import UserRepository
from backend.app.schemas import (
    Order,
    OrderStatus,
    Position,
    Signal,
    TradeAction,
)
from backend.app.services.bingx_account_service import BingXAccountService
from backend.app.services.bot_control_service import BotControlService
from backend.app.services.order_service import OrderService
from backend.app.schemas import BotSettingsUpdate


@pytest.mark.asyncio
async def test_build_signature_matches_reference() -> None:
    params = {"symbol": "BTCUSDT", "timestamp": 1234567890}
    assert build_signature("secret", params) == build_signature("secret", params)


@pytest.mark.asyncio
async def test_rest_client_signed_request() -> None:
    recorded: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        recorded["headers"] = dict(request.headers)
        recorded["query"] = dict(request.url.params)
        return httpx.Response(200, json={"data": {"success": True}})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="https://example.com") as client:
        rest = BingXRESTClient("key", "secret", client=client)
        await rest.get_positions("BTCUSDT")
    assert recorded["headers"]["X-BX-APIKEY"] == "key"
    assert "signature" in recorded["query"]


@pytest.mark.asyncio
async def test_order_service_retries_and_updates(session_factory) -> None:
    settings = get_settings()
    async with session_factory() as session:
        user_repo = UserRepository(session)
        bot_repo = BotSessionRepository(session)
        signal_repo = SignalRepository(session)
        order_repo = OrderRepository(session)

        user = await user_repo.get_or_create_by_username("order-user")
        bot_session = await bot_repo.get_or_create_active_session(user.id, "order-session")
        signal = await signal_repo.create(
            Signal(
                symbol="BTCUSDT",
                action=TradeAction.BUY,
                timestamp=datetime.now(timezone.utc),
                quantity=1.0,
                raw_payload={},
            )
        )
        order = await order_repo.create(
            Order(
                signal_id=signal.id,
                user_id=user.id,
                bot_session_id=bot_session.id,
                symbol="BTCUSDT",
                action=TradeAction.BUY,
                quantity=1.0,
            )
        )
        order_id = order.id

    async with session_factory() as session:
        order_repo = OrderRepository(session)
        position_repo = PositionRepository(session)
        payload = {
            "order_id": order_id,
            "symbol": "BTCUSDT",
            "action": TradeAction.BUY.value,
            "quantity": 1.0,
            "margin_mode": "isolated",
            "leverage": 5,
        }
        client = AsyncMock(spec=BingXRESTClient)
        client.set_margin_mode.return_value = {}
        client.set_leverage.return_value = {}
        client.create_order.side_effect = [
            BingXRESTError("temp failure"),
            {"orderId": "123", "avgPrice": "100"},
        ]
        service = OrderService(order_repo, position_repo, client, settings, asyncio.Queue(), max_retries=3)
        await service.handle_signal(payload)
        updated = await order_repo.get(order_id)
        assert updated.status == OrderStatus.SUBMITTED
        assert updated.exchange_order_id == "123"
        assert client.create_order.await_count == 2


@pytest.mark.asyncio
async def test_bot_control_service_triggers_bingx_sync(session_factory) -> None:
    settings = get_settings()
    async with session_factory() as session:
        signal_repo = SignalRepository(session)
        user_repo = UserRepository(session)
        bot_repo = BotSessionRepository(session)
        await signal_repo.create(
            Signal(
                symbol="ETHUSDT",
                action=TradeAction.BUY,
                timestamp=datetime.now(timezone.utc),
                quantity=1.0,
                raw_payload={},
            )
        )
        account_service = AsyncMock(spec=BingXAccountService)
        service = BotControlService(signal_repo, user_repo, bot_repo, settings, account_service)
        await service.update_state(BotSettingsUpdate(margin_mode="cross", leverage=10))
        account_service.ensure_preferences.assert_awaited()


@pytest.mark.asyncio
async def test_bingx_sync_service_resolves_positions(session_factory) -> None:
    async with session_factory() as session:
        user_repo = UserRepository(session)
        bot_repo = BotSessionRepository(session)
        signal_repo = SignalRepository(session)
        order_repo = OrderRepository(session)
        position_repo = PositionRepository(session)

        user = await user_repo.get_or_create_by_username("sync-user")
        bot_session = await bot_repo.get_or_create_active_session(user.id, "sync-session")
        signal = await signal_repo.create(
            Signal(
                symbol="BTCUSDT",
                action=TradeAction.BUY,
                timestamp=datetime.now(timezone.utc),
                quantity=1.0,
                raw_payload={},
            )
        )
        await order_repo.create(
            Order(
                signal_id=signal.id,
                user_id=user.id,
                bot_session_id=bot_session.id,
                symbol="BTCUSDT",
                action=TradeAction.BUY,
                quantity=1.0,
                exchange_order_id="abc",
            )
        )
        await position_repo.create(
            Position(
                user_id=user.id,
                bot_session_id=bot_session.id,
                symbol="BTCUSDT",
                action=TradeAction.BUY,
                quantity=1.0,
                entry_price=100.0,
            )
        )

    async with session_factory() as session:
        order_repo = OrderRepository(session)
        position_repo = PositionRepository(session)
        client = AsyncMock(spec=BingXRESTClient)
        client.get_all_orders.return_value = [
            {
                "symbol": "BTCUSDT",
                "orderId": "abc",
                "status": "FILLED",
                "side": "BUY",
                "avgPrice": "105",
                "origQty": "1",
            }
        ]
        client.get_positions.return_value = [
            {
                "symbol": "BTCUSDT",
                "positionAmt": "0",
                "positionSide": "LONG",
                "entryPrice": "105",
                "leverage": "5",
            }
        ]
        service = BingXSyncService(client, order_repo, position_repo)
        await service.resync_orders()
        await service.resync_positions()
        updated_order = await order_repo.get_by_exchange_order_id("abc")
        assert updated_order.status == OrderStatus.FILLED
        position_obj = await position_repo.get_open_by_symbol("BTCUSDT")
        assert position_obj is None
