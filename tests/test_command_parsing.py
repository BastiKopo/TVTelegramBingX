"""Tests for Telegram command argument parsing helpers."""

from __future__ import annotations

import pytest

from bot.state import BotState
from bot.telegram_bot import (
    CommandUsageError,
    ManualOrderRequest,
    _format_futures_settings_summary,
    _parse_leverage_command_args,
    _parse_margin_command_args,
    _parse_manual_order_args,
)


@pytest.mark.parametrize(
    "args,expected",
    [
        (("BTCUSDT", "cross", "USDT"), ("BTC-USDT", True, "cross", "USDT")),
        (("BTCUSDT", "USDT", "isolated"), ("BTC-USDT", True, "isolated", "USDT")),
        (("cross", "USDT"), (None, False, "cross", "USDT")),
        (("USDT", "isolated"), (None, False, "isolated", "USDT")),
        (("10",), (None, False, "cross", "10")),
    ],
)
def test_parse_margin_command_args_handles_flexible_order(args, expected) -> None:
    """Margin parser accepts symbol/coin in any position."""

    result = _parse_margin_command_args(args, default_mode="cross", default_coin="USDT")
    assert result == expected


@pytest.mark.parametrize(
    "args",
    [(), ("BTCUSDT",), ("BTCUSDT", "coin"), ("10", "extra")],
)
def test_parse_margin_command_args_rejects_invalid_payload(args) -> None:
    """Invalid margin command payloads raise ``CommandUsageError``."""

    with pytest.raises(CommandUsageError):
        _parse_margin_command_args(args)


@pytest.mark.parametrize(
    "args,expected",
    [
        (("BTCUSDT", "10", "USDT"), ("BTC-USDT", True, 10.0, "USDT", "cross")),
        (("BTCUSDT", "USDT", "10"), ("BTC-USDT", True, 10.0, "USDT", "cross")),
        (("10", "BTCUSDT", "USDT"), ("BTC-USDT", True, 10.0, "USDT", "cross")),
        (("10", "USDT"), (None, False, 10.0, "USDT", "cross")),
        (("isolated", "10"), (None, False, 10.0, None, "isolated")),
        (("10", "isolated"), (None, False, 10.0, None, "isolated")),
    ],
)
def test_parse_leverage_command_args_identifies_components(args, expected) -> None:
    """Leverage parser finds leverage, symbol and optional margin coin."""

    result = _parse_leverage_command_args(args, default_mode="cross", default_coin=None)
    assert result == expected


@pytest.mark.parametrize(
    "args",
    [(), ("BTCUSDT", "coin"), ("BTCUSDT", "USDT")],
)
def test_parse_leverage_command_args_requires_numeric_value(args) -> None:
    """Leverage parser raises ``CommandUsageError`` without a numeric value."""

    with pytest.raises(CommandUsageError):
        _parse_leverage_command_args(args)


def test_parse_leverage_command_args_rejects_non_positive_values() -> None:
    """Leverage must be strictly positive."""

    with pytest.raises(CommandUsageError):
        _parse_leverage_command_args(("BTCUSDT", "0"))


def test_format_futures_settings_summary_includes_state_values() -> None:
    """The futures summary surfaces the stored leverage and margin defaults."""

    state = BotState(margin_mode="isolated", margin_asset="busd", leverage=12.5)

    summary = _format_futures_settings_summary(state)

    assert "ISOLATED" in summary
    assert "BUSD" in summary
    assert "12.5x" in summary


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
