from datetime import datetime, timezone

import pytest


@pytest.mark.asyncio
async def test_bot_status_defaults(client):
    response = await client.get("/bot/status")
    assert response.status_code == 200
    payload = response.json()
    assert payload["auto_trade_enabled"] is False
    assert payload["manual_confirmation_required"] is True
    assert payload["margin_mode"] in {"isolated", "cross"}
    assert payload["leverage"] >= 1


@pytest.mark.asyncio
async def test_bot_settings_persist(client):
    update_response = await client.post(
        "/bot/settings",
        json={
            "auto_trade_enabled": True,
            "manual_confirmation_required": False,
            "margin_mode": "isolated",
            "leverage": 12,
        },
    )
    assert update_response.status_code == 200, update_response.text
    data = update_response.json()
    assert data["auto_trade_enabled"] is True
    assert data["manual_confirmation_required"] is False
    assert data["margin_mode"] == "isolated"
    assert data["leverage"] == 12

    status_response = await client.get("/bot/status")
    assert status_response.status_code == 200
    status_data = status_response.json()
    assert status_data["auto_trade_enabled"] is True
    assert status_data["manual_confirmation_required"] is False
    assert status_data["margin_mode"] == "isolated"
    assert status_data["leverage"] == 12


@pytest.mark.asyncio
async def test_bot_reports_returns_recent_signals(client):
    payload = {
        "symbol": "ADAUSDT",
        "action": "buy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "quantity": 15.0,
    }
    response = await client.post(
        "/webhook/tradingview",
        json=payload,
        headers={"X-TRADINGVIEW-TOKEN": "test-token"},
    )
    assert response.status_code == 201, response.text

    report_response = await client.get("/bot/reports", params={"limit": 1})
    assert report_response.status_code == 200
    reports = report_response.json()
    assert len(reports) == 1
    assert reports[0]["symbol"] == "ADAUSDT"
