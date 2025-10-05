from datetime import datetime, timezone

import pytest


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
async def test_accepts_valid_signal(client, signal_queue):
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
    assert channel == "signals.validated"
    assert message["symbol"] == "ETHUSDT"
    assert message["leverage"] == 3

    list_response = await client.get("/signals")
    assert list_response.status_code == 200
    items = list_response.json()
    assert any(item["symbol"] == "ETHUSDT" for item in items)
