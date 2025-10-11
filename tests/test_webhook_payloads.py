from __future__ import annotations

import time

import pytest

from webhook.payloads import (
    DeduplicationCache,
    build_deduplication_key,
    safe_parse_tradingview,
)


def test_safe_parse_tradingview_parses_json_payload() -> None:
    payload = safe_parse_tradingview(
        """
        {
          "symbol": "ltcusdt",
          "action": "long_open",
          "margin_usdt": "5",
          "lev": "50",
          "alert_id": "abc123",
          "bar_time": "2024-01-01T00:00:00Z"
        }
        """
    )

    assert payload["symbol"] == "LTC-USDT"
    assert payload["action"] == "LONG_OPEN"
    assert payload["margin_usdt"] == 5
    assert payload["lev"] == 50
    assert payload["alert_id"] == "abc123"
    assert payload["bar_time"] == "2024-01-01T00:00:00Z"


def test_safe_parse_tradingview_parses_key_value_payload() -> None:
    payload = safe_parse_tradingview(
        "symbol=BTCUSDT;action=short_close;margin=3.5;lev=25;alert_id=test-1;bar_time=2024-05-05T10:00:00Z"
    )

    assert payload["symbol"] == "BTC-USDT"
    assert payload["action"] == "SHORT_CLOSE"
    assert payload["margin_usdt"] == 3.5
    assert payload["lev"] == 25
    assert payload["alert_id"] == "test-1"
    assert payload["bar_time"] == "2024-05-05T10:00:00Z"


def test_safe_parse_tradingview_rejects_invalid_payload() -> None:
    with pytest.raises(ValueError):
        safe_parse_tradingview("just some text without separators")


def test_build_deduplication_key_prefers_bar_time() -> None:
    payload = {
        "symbol": "ETHUSDT",
        "action": "BUY",
        "bar_time": "2024-07-07T12:34:56Z",
    }

    key = build_deduplication_key(payload)
    assert key == "ETH-USDT|long|2024-07-07T12:34:56Z"


def test_deduplication_cache_detects_duplicates(monkeypatch: pytest.MonkeyPatch) -> None:
    cache = DeduplicationCache(ttl_seconds=1.0)

    current = 1_000.0

    def _fake_monotonic() -> float:
        return current

    monkeypatch.setattr(time, "monotonic", _fake_monotonic)

    assert cache.seen("key") is False
    assert cache.seen("key") is True

    current += 2.0
    assert cache.seen("key") is False
