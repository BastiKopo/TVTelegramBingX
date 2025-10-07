"""Tests for the persistent bot state helpers."""

import json

from bot.state import (
    BotState,
    GlobalTradeConfig,
    export_state_snapshot,
    load_state_snapshot,
)


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


def test_bot_state_serialises_global_trade_config() -> None:
    """Global trade settings are persisted and restored."""

    state = BotState(
        global_trade=GlobalTradeConfig(
            margin_usdt=200,
            lev_long=3,
            lev_short=4,
            isolated=False,
            hedge_mode=True,
        )
    )

    payload = state.to_dict()
    assert payload["global_trade"] == {
        "margin_usdt": 200,
        "lev_long": 3,
        "lev_short": 4,
        "isolated": False,
        "hedge_mode": True,
    }

    restored = BotState.from_mapping(payload)
    assert restored.global_trade.margin_usdt == 200
    assert restored.global_trade.lev_long == 3
    assert restored.global_trade.lev_short == 4
    assert restored.global_trade.isolated is False
    assert restored.global_trade.hedge_mode is True


def test_bot_state_from_mapping_normalises_last_symbol() -> None:
    """Loading from legacy payloads strips exchange prefixes and uppercases."""

    payload = {"last_symbol": "binance:btc-usdt"}

    state = BotState.from_mapping(payload)

    assert state.last_symbol == "BTC-USDT"


def test_bot_state_from_mapping_defaults_margin_asset() -> None:
    """Missing margin assets default to USDT."""

    state = BotState.from_mapping({})

    assert state.normalised_margin_asset() == "USDT"


def test_export_state_snapshot_contains_normalised_values(tmp_path) -> None:
    """Snapshots expose the normalised margin and leverage configuration."""

    state = BotState(
        autotrade_enabled=True,
        margin_mode="isolated",
        margin_asset="busd",
        leverage=12,
        max_trade_size=25.5,
        daily_report_time="18:30",
        last_symbol="ethusdt",
    )

    snapshot_path = tmp_path / "state.json"
    export_state_snapshot(state, path=snapshot_path)

    payload = json.loads(snapshot_path.read_text(encoding="utf-8"))

    assert payload["autotrade_enabled"] is True
    assert payload["margin_mode"] == "ISOLATED"
    assert payload["margin_coin"] == "BUSD"
    assert payload["leverage"] == 12
    assert payload["max_trade_size"] == 25.5
    assert payload["daily_report_time"] == "18:30"
    assert payload["last_symbol"] == "ETHUSDT"
    assert "global_trade" in payload


def test_load_state_snapshot_reads_written_payload(tmp_path) -> None:
    """Snapshots can be reloaded from disk for downstream consumers."""

    payload = {
        "autotrade_enabled": True,
        "margin_mode": "ISOLATED",
        "margin_coin": "USDT",
        "leverage": 5,
    }

    snapshot_path = tmp_path / "state.json"
    snapshot_path.write_text(json.dumps(payload), encoding="utf-8")

    assert load_state_snapshot(path=snapshot_path) == payload
