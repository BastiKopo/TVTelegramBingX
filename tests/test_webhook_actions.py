from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

from tvtelegrambingx.webhook import server
from tvtelegrambingx.webhook.server import _iter_actions


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("long_buy", ["LONG_BUY"]),
        ("long_buy, short_sell", ["LONG_BUY", "SHORT_SELL"]),
        (["long_buy", "short_buy"], ["LONG_BUY", "SHORT_BUY"]),
        ("long_buy short_buy", ["LONG_BUY", "SHORT_BUY"]),
        ("long_buy;short_sell", ["LONG_BUY", "SHORT_SELL"]),
        (["long_buy", "LONG_BUY"], ["LONG_BUY"]),
        (["long_buy", ["short_sell", "long_buy"]], ["LONG_BUY", "SHORT_SELL"]),
        ("long_buy\nshort_sell\nlong_buy", ["LONG_BUY", "SHORT_SELL"]),
        (None, []),
    ],
)
def test_iter_actions_variants(raw, expected):
    assert list(_iter_actions(raw)) == expected


@pytest.fixture
def test_client():
    return TestClient(server.app)


def test_webhook_accepts_iterable_actions(monkeypatch, test_client):
    received = []

    async def fake_handle_signal(payload):
        received.append(payload)

    monkeypatch.setattr(server, "handle_signal", fake_handle_signal)

    response = test_client.post(
        "/tradingview-webhook",
        json={
            "secret": server.SECRET,
            "symbol": "BTCUSDT",
            "actions": ["long_buy", ["short_sell", "long_buy"]],
        },
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert len(received) == 1

    payload = received[0]
    assert payload["symbol"] == "BTCUSDT"
    assert payload["actions"] == ["LONG_BUY", "SHORT_SELL"]
    assert payload["action"] == "LONG_BUY"
    assert isinstance(payload["timestamp"], int)
