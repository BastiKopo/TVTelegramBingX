"""Tests for Telegram command argument parsing helpers."""

from __future__ import annotations

import pytest

from bot.state import BotState
from bot.telegram_bot import (
    CommandUsageError,
    ManualOrderRequest,
    QuickTradeArguments,
    _format_futures_settings_summary,
    _parse_manual_order_args,
    _parse_quick_trade_arguments,
    _quick_trade_request_from_args,
)


def test_parse_quick_trade_arguments_requires_symbol() -> None:
    """Quick trade parser enforces a trading symbol."""

    with pytest.raises(CommandUsageError, match="Bitte Symbol angeben"):
        _parse_quick_trade_arguments([], default_tif="GTC")


def test_parse_quick_trade_arguments_supports_client_id() -> None:
    """Client order IDs are preserved when parsing quick trade options."""

    args = ["BTCUSDT", "--clid", "custom-123", "--tif", "IOC"]
    trade = _parse_quick_trade_arguments(args, default_tif="IOC")

    assert isinstance(trade, QuickTradeArguments)
    assert trade.symbol == "BTCUSDT"
    assert trade.client_order_id == "custom-123"
    assert trade.time_in_force == "IOC"


def test_quick_trade_request_keeps_client_order_id() -> None:
    """The generated manual request forwards the parsed client order ID."""

    state = BotState()
    trade = QuickTradeArguments(
        symbol="ETHUSDT",
        quantity=0.5,
        limit_price=None,
        time_in_force="GTC",
        client_order_id="alpha",
    )

    request = _quick_trade_request_from_args(state, trade, reduce_only=False)

    assert isinstance(request, ManualOrderRequest)
    assert request.client_order_id == "alpha"


def test_parse_manual_order_args_accepts_margin_budget() -> None:
    """Manual order parser accepts margin-based sizing with overrides."""

    request = _parse_manual_order_args(
        [
            "BTCUSDT",
            "--margin",
            "300",
            "--lev",
            "12",
            "--limit",
            "27850",
            "--tif",
            "fok",
            "--reduce-only",
            "0",
            "--clid",
            "beta",
            "LONG",
        ]
    )

    assert isinstance(request, ManualOrderRequest)
    assert request.symbol == "BTCUSDT"
    assert request.margin == 300
    assert request.quantity is None
    assert request.leverage == 12
    assert request.limit_price == 27850
    assert request.time_in_force == "FOK"
    assert request.reduce_only is False
    assert request.direction == "LONG"
    assert request.client_order_id == "beta"


def test_parse_manual_order_args_supports_qty_shortcuts() -> None:
    """Manual parser keeps positional quantities and defaults reduce-only."""

    request = _parse_manual_order_args(["ETHUSDT", "0.25", "SHORT"])

    assert request.symbol == "ETHUSDT"
    assert request.quantity == 0.25
    assert request.margin is None
    assert request.leverage is None
    assert request.direction == "SHORT"


def test_parse_manual_order_args_requires_sizing_input() -> None:
    """Missing margin and quantity raises a usage error."""

    with pytest.raises(CommandUsageError, match="--qty oder --margin"):
        _parse_manual_order_args(["BTCUSDT", "LONG"])


def test_format_futures_settings_summary_includes_state_values() -> None:
    """The futures summary surfaces the stored leverage and margin defaults."""

    state = BotState(margin_mode="isolated", margin_asset="busd", leverage=12.5)

    summary = _format_futures_settings_summary(state)

    assert "ISOLATED" in summary
    assert "BUSD" in summary
    assert "12.5x" in summary
