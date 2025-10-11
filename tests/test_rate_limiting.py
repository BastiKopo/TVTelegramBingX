from __future__ import annotations

import asyncio

import pytest

from services import trading


def test_throttle_symbol_enforces_minimum_delay(monkeypatch: pytest.MonkeyPatch) -> None:
    """Subsequent orders for the same symbol wait for the configured delay."""

    recorded_sleeps: list[float] = []

    async def _fake_sleep(delay: float) -> None:  # pragma: no cover - patched in test
        recorded_sleeps.append(delay)

    timeline = iter([100.0, 100.1, 100.25, 100.6])

    monkeypatch.setattr(trading.asyncio, "sleep", _fake_sleep)
    monkeypatch.setattr(trading, "_monotonic", lambda: next(timeline))
    monkeypatch.setattr(trading, "_SYMBOL_THROTTLE_SECONDS", 0.25)
    monkeypatch.setattr(trading, "_SYMBOL_THROTTLE_LOCKS", {})
    monkeypatch.setattr(trading, "_LAST_SYMBOL_ORDER", {})

    async def _runner() -> None:
        await trading._throttle_symbol("BTC-USDT")
        await trading._throttle_symbol("BTC-USDT")
        await trading._throttle_symbol("BTC-USDT")

    asyncio.run(_runner())

    assert recorded_sleeps == pytest.approx([0.15], abs=1e-9)


def test_throttle_symbol_handles_parallel_symbols(monkeypatch: pytest.MonkeyPatch) -> None:
    """Separate symbols maintain independent timers."""

    lock_store: dict[int, asyncio.Lock] = {}
    order_store: dict[int, dict[str, float]] = {}
    timeline = iter([200.0, 200.05, 200.1, 200.15])

    async def _fake_sleep(delay: float) -> None:  # pragma: no cover - patched in test
        raise AssertionError(f"Unexpected sleep: {delay}")

    monkeypatch.setattr(trading.asyncio, "sleep", _fake_sleep)
    monkeypatch.setattr(trading, "_monotonic", lambda: next(timeline))
    monkeypatch.setattr(trading, "_SYMBOL_THROTTLE_SECONDS", 0.25)
    monkeypatch.setattr(trading, "_SYMBOL_THROTTLE_LOCKS", lock_store)
    monkeypatch.setattr(trading, "_LAST_SYMBOL_ORDER", order_store)

    async def _runner() -> None:
        await asyncio.gather(
            trading._throttle_symbol("BTC-USDT"),
            trading._throttle_symbol("ETH-USDT"),
        )

    asyncio.run(_runner())

    assert len(order_store) == 1
    symbol_map = next(iter(order_store.values()))
    assert set(symbol_map.keys()) == {"BTC-USDT", "ETH-USDT"}
