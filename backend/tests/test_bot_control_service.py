from __future__ import annotations

from datetime import datetime, timezone

import pytest

from backend.app import config
from backend.app.repositories.balance_repository import BalanceRepository
from backend.app.repositories.bot_session_repository import BotSessionRepository
from backend.app.repositories.order_repository import OrderRepository
from backend.app.repositories.position_repository import PositionRepository
from backend.app.repositories.signal_repository import SignalRepository
from backend.app.repositories.user_repository import UserRepository
from backend.app.schemas import (
    BotSettingsUpdate,
    Order,
    OrderStatus,
    Position,
    Signal,
    TradeAction,
)
from backend.app.services.bot_control_service import BotControlService


@pytest.mark.asyncio
async def test_bot_state_includes_aggregated_metrics(session_factory):
    settings = config.get_settings()
    async with session_factory() as session:
        signal_repository = SignalRepository(session)
        user_repository = UserRepository(session)
        bot_session_repository = BotSessionRepository(session)
        balance_repository = BalanceRepository(session)
        position_repository = PositionRepository(session)
        order_repository = OrderRepository(session)

        service = BotControlService(
            signal_repository,
            user_repository,
            bot_session_repository,
            balance_repository,
            position_repository,
            settings,
            order_repository=order_repository,
        )

        user = await user_repository.get_or_create_by_username(settings.trading_default_username)
        session_entity = await bot_session_repository.get_or_create_active_session(
            user.id, settings.trading_default_session
        )

        await balance_repository.upsert(user.id, "USDT", free=150.0, locked=25.0)

        position = Position(
            user_id=user.id,
            bot_session_id=session_entity.id,
            symbol="BTCUSDT",
            action=TradeAction.BUY,
            quantity=0.5,
            entry_price=21000.0,
            leverage=3,
        )
        await position_repository.create(position)

        signal = Signal(
            symbol="BTCUSDT",
            action=TradeAction.SELL,
            timestamp=datetime.now(timezone.utc),
            quantity=0.5,
            raw_payload={"source": "test"},
        )
        stored_signal = await signal_repository.create(signal)

        order = Order(
            signal_id=stored_signal.id,
            user_id=user.id,
            bot_session_id=session_entity.id,
            symbol="BTCUSDT",
            action=TradeAction.SELL,
            status=OrderStatus.FILLED,
            quantity=0.5,
            price=21500.0,
        )
        await order_repository.create(order)

        state = await service.get_state()

        assert state.balances and state.balances[0].asset == "USDT"
        assert state.balances[0].total == pytest.approx(175.0)
        assert state.pnl.realized == pytest.approx(10750.0)
        assert state.pnl.total == pytest.approx(10750.0)
        assert state.open_positions and state.open_positions[0].symbol == "BTCUSDT"


@pytest.mark.asyncio
async def test_update_state_preserves_metrics(session_factory):
    settings = config.get_settings()
    async with session_factory() as session:
        signal_repository = SignalRepository(session)
        user_repository = UserRepository(session)
        bot_session_repository = BotSessionRepository(session)
        balance_repository = BalanceRepository(session)
        position_repository = PositionRepository(session)
        order_repository = OrderRepository(session)

        service = BotControlService(
            signal_repository,
            user_repository,
            bot_session_repository,
            balance_repository,
            position_repository,
            settings,
            order_repository=order_repository,
        )

        await service.get_state()  # initialize session context

        update = BotSettingsUpdate(auto_trade_enabled=True)
        state = await service.update_state(update)

        assert state.auto_trade_enabled is True
        assert state.pnl.total == pytest.approx(0.0)
        assert state.balances == []
