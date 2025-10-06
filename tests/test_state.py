"""Tests for the persistent bot state helpers."""

from bot.state import BotState


def test_bot_state_to_dict_uppercases_last_symbol() -> None:
    """The state serialiser stores symbols in uppercase without prefixes."""

    state = BotState(last_symbol="ethusdt")

    payload = state.to_dict()

    assert payload["last_symbol"] == "ETHUSDT"


def test_bot_state_to_dict_includes_margin_asset() -> None:
    """Margin assets are persisted in uppercase for reuse."""

    state = BotState(margin_asset="busd")

    payload = state.to_dict()

    assert payload["margin_asset"] == "BUSD"


def test_bot_state_from_mapping_normalises_last_symbol() -> None:
    """Loading from legacy payloads strips exchange prefixes and uppercases."""

    payload = {"last_symbol": "binance:btc-usdt"}

    state = BotState.from_mapping(payload)

    assert state.last_symbol == "BTC-USDT"


def test_bot_state_from_mapping_defaults_margin_asset() -> None:
    """Missing margin assets default to USDT."""

    state = BotState.from_mapping({})

    assert state.normalised_margin_asset() == "USDT"
