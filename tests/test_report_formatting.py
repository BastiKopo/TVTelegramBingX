"""Tests for report formatting helpers."""

from bot.telegram_bot import _format_balance_payload, _format_margin_payload


def test_format_balance_payload_skips_usdc_entries() -> None:
    payload = [
        {"currency": "USDT", "equity": 100, "availableMargin": 50},
        {"currency": "USDC", "equity": 80, "availableMargin": 40},
    ]

    lines = _format_balance_payload(payload)

    combined = "\n".join(lines)
    assert "USDC" not in combined
    assert "USDT" in combined


def test_format_margin_payload_skips_usdc_entries() -> None:
    payload = [
        {"symbol": "USDT", "availableMargin": 25, "usedMargin": 5},
        {"symbol": "USDC", "availableMargin": 12, "usedMargin": 3},
    ]

    message = _format_margin_payload(payload)

    assert "USDC" not in message
    assert "USDT" in message
