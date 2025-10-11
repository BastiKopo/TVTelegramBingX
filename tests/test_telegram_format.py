"""Tests for the unified Telegram signal message formatter."""

from __future__ import annotations

from datetime import datetime

from integrations.telegram_format import build_signal_message


def test_build_signal_message_for_long_open() -> None:
    """Messages for opening long positions follow the documented layout."""

    message = build_signal_message(
        symbol="BTC-USDT",
        intent="long_open",
        order_type="Market",
        position_side="long",
        auto_trade=True,
        leverage=20,
        margin_usdt=10,
        timestamp=datetime(2025, 10, 10, 22, 44, 11),
    )

    assert message == (
        "🟢 SIGNAL - Buy\n"
        "------------------------\n"
        "Asset: BTC-USDT\n"
        "Margin: 10 USDT\n"
        "Leverage: 20x\n"
        "Auto-trade: On\n"
        "Entry Type: Market\n"
        "Position Side: LONG\n"
        "Timestamp: 2025-10-10 22:44:11"
    )


def test_build_signal_message_for_close_short() -> None:
    """Closing shorts includes reduce-only exit information and quantity fallbacks."""

    message = build_signal_message(
        symbol="ETH-USDT",
        intent="short_close",
        order_type="Market",
        position_side="SHORT",
        auto_trade=False,
        leverage=None,
        margin_usdt=None,
        quantity="25",
        reduce_only=True,
        timestamp=datetime(2024, 12, 31, 23, 59, 59),
    )

    assert message == (
        "⚫ SIGNAL - Close Short\n"
        "------------------------\n"
        "Asset: ETH-USDT\n"
        "Quantity: 25\n"
        "Auto-trade: Off\n"
        "Exit Type: Market (Reduce Only)\n"
        "Position Side: SHORT\n"
        "Timestamp: 2024-12-31 23:59:59"
    )
