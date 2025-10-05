from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlmodel import select

from backend.app.repositories import (
    BalanceRepository,
    BotSessionRepository,
    OrderRepository,
    PositionRepository,
    SignalRepository,
    UserRepository,
)
from backend.app.schemas import (
    Balance,
    BotSessionStatus,
    Order,
    OrderStatus,
    Position,
    PositionStatus,
    Signal,
    TradeAction,
)


@pytest.mark.asyncio
async def test_repository_crud_roundtrip(session_factory):
    async with session_factory() as session:
        user_repo = UserRepository(session)
        bot_session_repo = BotSessionRepository(session)
        signal_repo = SignalRepository(session)
        order_repo = OrderRepository(session)
        balance_repo = BalanceRepository(session)
        position_repo = PositionRepository(session)

        user = await user_repo.get_or_create_by_username("repository-user")
        assert user.id is not None

        bot_session = await bot_session_repo.get_or_create_active_session(user.id, "session-a")
        assert bot_session.status == BotSessionStatus.ACTIVE

        signal = Signal(
            symbol="BTCUSDT",
            action=TradeAction.BUY,
            confidence=0.9,
            timestamp=datetime.now(timezone.utc),
            quantity=0.5,
            raw_payload={"symbol": "BTCUSDT", "action": "buy", "quantity": 0.5},
        )
        stored_signal = await signal_repo.create(signal)
        assert stored_signal.id is not None

        order = Order(
            signal_id=stored_signal.id,
            user_id=user.id,
            bot_session_id=bot_session.id,
            symbol="BTCUSDT",
            action=TradeAction.BUY,
            quantity=0.5,
        )
        stored_order = await order_repo.create(order)
        assert stored_order.status == OrderStatus.PENDING

        updated_order = await order_repo.update_status(
            stored_order,
            OrderStatus.SUBMITTED,
            price=25000.0,
            exchange_order_id="abc-123",
        )
        assert updated_order.status == OrderStatus.SUBMITTED
        assert updated_order.price == 25000.0
        assert updated_order.exchange_order_id == "abc-123"

        first_balance = await balance_repo.upsert(user.id, "USDT", free=1000.0, locked=50.0)
        assert isinstance(first_balance, Balance)
        second_balance = await balance_repo.upsert(user.id, "USDT", free=900.0, locked=25.0)
        assert second_balance.id == first_balance.id
        assert second_balance.free == 900.0

        position = Position(
            user_id=user.id,
            bot_session_id=bot_session.id,
            symbol="BTCUSDT",
            action=TradeAction.BUY,
            quantity=0.25,
            entry_price=24500.0,
            leverage=5,
        )
        stored_position = await position_repo.create(position)
        await position_repo.close_position(stored_position, status=PositionStatus.CLOSED)
        assert stored_position.status == PositionStatus.CLOSED
        assert stored_position.closed_at is not None

        orders_for_signal = await order_repo.list_for_signal(stored_signal.id)
        assert len(orders_for_signal) == 1

        result = await session.exec(select(Balance).where(Balance.user_id == user.id))
        balances = result.all()
        assert len(balances) == 1
