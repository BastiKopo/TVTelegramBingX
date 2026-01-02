"""Tests for the Freqtrade configuration migrator utilities."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tvtelegrambingx.utils.freqtrade_config_migrator import (  # noqa: E402
    migrate_static_pairlist_whitelist,
)


def test_migrate_static_pairlist_adds_missing_whitelist() -> None:
    config = {
        "pairlists": [{"method": "StaticPairList"}],
        "pair_whitelist": ["BTC/USDC", "ETH/USDC"],
    }

    result = migrate_static_pairlist_whitelist(config)

    assert result.changed is True
    pairlist = result.data["pairlists"][0]
    assert pairlist["config"]["pair_whitelist"] == ["BTC/USDC", "ETH/USDC"]


def test_migrate_static_pairlist_is_idempotent() -> None:
    config = {
        "pairlists": [
            {
                "method": "StaticPairList",
                "config": {"pair_whitelist": ["BTC/USDC"]},
            }
        ],
        "pair_whitelist": ["BTC/USDC"],
    }

    original = deepcopy(config)
    first = migrate_static_pairlist_whitelist(config)
    second = migrate_static_pairlist_whitelist(first.data)

    assert first.changed is False
    assert second.changed is False
    assert first.data == original
    assert second.data == original
