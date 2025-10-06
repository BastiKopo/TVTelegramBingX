"""Tests for Telegram command argument parsing helpers."""

from __future__ import annotations

import pytest

from bot.telegram_bot import (
    CommandUsageError,
    _parse_leverage_command_args,
    _parse_margin_command_args,
)


@pytest.mark.parametrize(
    "args,expected",
    [
        (("BTCUSDT", "cross", "USDT"), ("BTCUSDT", True, "cross", "USDT")),
        (("BTCUSDT", "USDT", "isolated"), ("BTCUSDT", True, "isolated", "USDT")),
        (("cross", "USDT"), (None, False, "cross", "USDT")),
        (("USDT", "isolated"), ("USDT", True, "isolated", None)),
    ],
)
def test_parse_margin_command_args_handles_flexible_order(args, expected) -> None:
    """Margin parser accepts symbol/coin in any position."""

    result = _parse_margin_command_args(args)
    assert result == expected


@pytest.mark.parametrize(
    "args",
    [(), ("BTCUSDT",), ("BTCUSDT", "coin")],
)
def test_parse_margin_command_args_rejects_invalid_payload(args) -> None:
    """Invalid margin command payloads raise ``CommandUsageError``."""

    with pytest.raises(CommandUsageError):
        _parse_margin_command_args(args)


@pytest.mark.parametrize(
    "args,expected",
    [
        (("BTCUSDT", "10", "USDT"), ("BTCUSDT", True, 10.0, "USDT")),
        (("BTCUSDT", "USDT", "10"), ("BTCUSDT", True, 10.0, "USDT")),
        (("10", "BTCUSDT", "USDT"), ("BTCUSDT", True, 10.0, "USDT")),
        (("10", "USDT"), (None, False, 10.0, "USDT")),
    ],
)
def test_parse_leverage_command_args_identifies_components(args, expected) -> None:
    """Leverage parser finds leverage, symbol and optional margin coin."""

    result = _parse_leverage_command_args(args)
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
