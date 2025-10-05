from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock

import pytest
from sqlmodel import select

from backend.app import config
from backend.app.integrations.telegram import InMemorySignalNotifier
from backend.app.schemas import Order, OrderStatus, Signal


@pytest.mark.asyncio
async def test_rejects_invalid_token(client):
    payload = {
        "symbol": "BTCUSDT",
        "action": "buy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "quantity": 0.1,
    }
    response = await client.post("/webhook/tradingview", json=payload, headers={"X-TRADINGVIEW-TOKEN": "wrong"})
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_accepts_valid_signal(client, signal_queue, session_factory, notifier):
    settings = config.get_settings()
    payload = {
        "symbol": "ETHUSDT",
        "action": "sell",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "quantity": 2.5,
        "confidence": 0.8,
        "leverage": 3,
        "margin_mode": "isolated",
    }
    response = await client.post(
        "/webhook/tradingview",
        json=payload,
        headers={"X-TRADINGVIEW-TOKEN": "test-token"},
    )
    assert response.status_code == 201, response.text
    data = response.json()
    assert data["symbol"] == "ETHUSDT"
    assert data["action"] == "sell"

    channel, message = await signal_queue.get()
    assert channel == settings.broker_validated_routing_key
    assert message["symbol"] == "ETHUSDT"
    assert message["leverage"] == 3

    list_response = await client.get("/signals")
    assert list_response.status_code == 200
    items = list_response.json()
    assert any(item["symbol"] == "ETHUSDT" for item in items)

    assert isinstance(notifier, InMemorySignalNotifier)
    notification = await notifier.queue.get()
    assert "ETHUSDT" in notification
    assert "SELL" in notification
    assert "margin=isolated" in notification
    assert "leverage=3x" in notification

    async with session_factory() as session:
        result = await session.exec(select(Order).where(Order.signal_id == data["id"]))
        orders = result.all()
    assert len(orders) == 1
    stored_order = orders[0]
    assert stored_order.symbol == "ETHUSDT"
    assert stored_order.status == OrderStatus.PENDING


@pytest.mark.asyncio
async def test_applies_defaults_when_fields_omitted(client, signal_queue, session_factory, notifier):
    payload = {
        "symbol": "BNBUSDT",
        "action": "buy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "quantity": 1.25,
    }

    response = await client.post(
        "/webhook/tradingview",
        json=payload,
        headers={"X-TRADINGVIEW-TOKEN": "test-token"},
    )

    assert response.status_code == 201, response.text

    settings = config.get_settings()

    channel, message = await signal_queue.get()
    assert channel == settings.broker_validated_routing_key
    assert message["leverage"] == settings.default_leverage
    assert message["margin_mode"] == settings.default_margin_mode

    async with session_factory() as session:
        result = await session.exec(select(Signal).where(Signal.symbol == "BNBUSDT"))
        stored_signal = result.one()

    assert stored_signal.leverage == settings.default_leverage
    assert stored_signal.margin_mode == settings.default_margin_mode

    assert isinstance(notifier, InMemorySignalNotifier)
    notification = await notifier.queue.get()
    assert "BNBUSDT" in notification
    assert f"margin={settings.default_margin_mode}" in notification
    assert f"leverage={settings.default_leverage}x" in notification


@pytest.mark.asyncio
async def test_publishes_to_broker_abstraction(client):
    from backend.app.main import app, get_publisher

    mock_publisher = SimpleNamespace(publish=AsyncMock())
    settings = config.get_settings()

    async def override_publisher() -> AsyncMock:
        return mock_publisher

    app.dependency_overrides[get_publisher] = override_publisher

    payload = {
        "symbol": "SOLUSDT",
        "action": "buy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "quantity": 0.75,
    }

    try:
        response = await client.post(
            "/webhook/tradingview",
            json=payload,
            headers={"X-TRADINGVIEW-TOKEN": "test-token"},
        )
    finally:
        app.dependency_overrides.pop(get_publisher, None)

    assert response.status_code == 201, response.text
    mock_publisher.publish.assert_awaited_once_with(
        settings.broker_validated_routing_key,
        ANY,
    )
