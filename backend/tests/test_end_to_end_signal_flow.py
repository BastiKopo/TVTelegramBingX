from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import datetime, timezone

import pytest

from backend.app import config
from backend.app.repositories.order_repository import OrderRepository
from backend.app.repositories.position_repository import PositionRepository
from backend.app.schemas import OrderStatus, TradeAction
from backend.app.services.order_service import OrderService


class StubBingXClient:
    """Test double for the BingX REST client."""

    def __init__(self) -> None:
        self.margin_calls: list[tuple[str, str]] = []
        self.leverage_calls: list[tuple[str, int]] = []
        self.orders: list[dict[str, object]] = []

    async def set_margin_mode(self, symbol: str, mode: str) -> None:
        self.margin_calls.append((symbol, mode))

    async def set_leverage(self, symbol: str, leverage: int) -> None:
        self.leverage_calls.append((symbol, leverage))

    async def create_order(self, request: dict[str, object]) -> dict[str, object]:
        self.orders.append(request)
        return {
            "orderId": "SIM-12345",
            "avgPrice": "101.25",
            "symbol": request.get("symbol"),
            "side": request.get("side"),
        }


@pytest.mark.asyncio
async def test_signal_reaches_execution_pipeline(
    client,
    signal_queue,
    session_factory,
):
    settings = config.get_settings()

    status_before = await client.get("/bot/status")
    assert status_before.status_code == 200
    payload = status_before.json()
    assert payload["manual_confirmation_required"] is True

    signal_payload = {
        "symbol": "BTCUSDT",
        "action": TradeAction.BUY.value,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "quantity": 0.01,
        "confidence": 0.9,
        "stop_loss": 48000.0,
        "take_profit": 52000.0,
    }

    response = await client.post(
        "/webhook/tradingview",
        json=signal_payload,
        headers={"X-TRADINGVIEW-TOKEN": "test-token"},
    )
    assert response.status_code == 201
    signal_data = response.json()
    assert signal_data["symbol"] == signal_payload["symbol"]

    channel, message = await asyncio.wait_for(signal_queue.get(), timeout=1)
    assert channel == settings.broker_validated_routing_key
    assert message["symbol"] == signal_payload["symbol"]
    assert message["order_id"] > 0

    update = await client.post(
        "/bot/settings",
        json={
            "auto_trade_enabled": True,
            "manual_confirmation_required": False,
        },
    )
    assert update.status_code == 200
    update_body = update.json()
    assert update_body["manual_confirmation_required"] is False
    assert update_body["auto_trade_enabled"] is True

    await signal_queue.put((channel, message))

    fake_client = StubBingXClient()
    worker_task = None
    try:
        async with session_factory() as session:
            order_repo = OrderRepository(session)
            position_repo = PositionRepository(session)
            service = OrderService(
                order_repo,
                position_repo,
                fake_client,
                settings,
                signal_queue,
                max_retries=1,
                backoff_base=0.05,
            )
            worker_task = asyncio.create_task(service.run())
            order = await _wait_for_order_status(session_factory, message["order_id"])
            assert order.status == OrderStatus.SUBMITTED
            assert order.exchange_order_id == "SIM-12345"
            assert order.price == pytest.approx(101.25)
            await service.stop()
    finally:
        if worker_task:
            worker_task.cancel()
            with suppress(asyncio.CancelledError):
                await worker_task

    assert fake_client.margin_calls == [(signal_payload["symbol"], settings.default_margin_mode)]
    assert fake_client.leverage_calls == [
        (signal_payload["symbol"], settings.default_leverage)
    ]
    assert fake_client.orders == [
        {
            "symbol": signal_payload["symbol"],
            "side": "BUY",
            "type": "MARKET",
            "quantity": pytest.approx(signal_payload["quantity"]),
        }
    ]


async def _wait_for_order_status(session_factory, order_id: int, *, timeout: float = 3.0):
    start = asyncio.get_running_loop().time()
    while True:
        async with session_factory() as session:
            repository = OrderRepository(session)
            order = await repository.get(order_id)
            if order and order.status == OrderStatus.SUBMITTED and order.exchange_order_id:
                return order
        if asyncio.get_running_loop().time() - start > timeout:
            raise AssertionError("Timed out waiting for order submission")
        await asyncio.sleep(0.05)
