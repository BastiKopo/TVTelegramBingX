"""Autonomous AI trading loop based on simple candlestick signals."""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Iterable, Optional

from tvtelegrambingx.ai.gatekeeper import _load_config
from tvtelegrambingx.config import Settings
from tvtelegrambingx.config_store import ConfigStore
from tvtelegrambingx.integrations import bingx_account

LOGGER = logging.getLogger(__name__)
CONFIG = ConfigStore()


def _sma(values: list[float]) -> Optional[float]:
    if not values:
        return None
    return sum(values) / len(values)


def _has_open_position(positions: Iterable[dict], symbol: str, action: str) -> bool:
    side = "LONG" if action == "LONG_BUY" else "SHORT"
    for entry in positions:
        if str(entry.get("symbol") or "").upper() != symbol.upper():
            continue
        position_side = str(entry.get("positionSide") or "").upper()
        if position_side and position_side != side:
            continue
        qty_raw = entry.get("positionAmt") or entry.get("positionSize") or 0
        try:
            qty = float(qty_raw)
        except (TypeError, ValueError):
            continue
        if abs(qty) > 0:
            return True
    return False


async def _evaluate_symbol(
    symbol: str,
    *,
    interval: str,
    limit: int,
) -> Optional[str]:
    klines = await bingx_account.get_klines(symbol, interval=interval, limit=limit)
    closes = [float(entry["close"]) for entry in klines if "close" in entry]
    if len(closes) < 21:
        return None

    short = _sma(closes[-5:])
    long = _sma(closes[-20:])
    prev_short = _sma(closes[-6:-1])
    prev_long = _sma(closes[-21:-1])
    if short is None or long is None or prev_short is None or prev_long is None:
        return None

    if prev_short <= prev_long and short > long:
        return "LONG_BUY"
    if prev_short >= prev_long and short < long:
        return "SHORT_SELL"
    return None


async def run_ai_autonomous(settings: Settings) -> None:
    """Run autonomous AI trading loop."""
    from tvtelegrambingx.bot.telegram_bot import handle_signal

    while True:
        interval = CONFIG.get_ai_autonomous_interval_seconds()
        if interval is None:
            interval = settings.ai_autonomous_interval_seconds
        interval = max(10, interval)

        enabled = CONFIG.get().get("_global", {}).get("ai_autonomous_enabled")
        if enabled is None:
            enabled = settings.ai_autonomous_enabled

        config = _load_config()
        if not enabled or not config.enabled or config.mode != "autonomous":
            await asyncio.sleep(interval)
            continue

        universe = config.universe
        if not universe:
            LOGGER.warning("AI autonomous mode enabled but universe is empty")
            await asyncio.sleep(interval)
            continue

        try:
            positions = await bingx_account.get_positions()
        except Exception:  # pragma: no cover - network/credentials
            LOGGER.exception("Failed to fetch positions for autonomous AI")
            positions = []

        for symbol in universe:
            try:
                action = await _evaluate_symbol(
                    symbol,
                    interval=settings.ai_autonomous_kline_interval,
                    limit=settings.ai_autonomous_kline_limit,
                )
            except Exception:  # pragma: no cover - network/invalid symbol
                LOGGER.exception("Failed to evaluate symbol for autonomous AI: %s", symbol)
                continue

            if action is None:
                continue
            if _has_open_position(positions, symbol, action):
                continue

            payload = {
                "symbol": symbol,
                "actions": [action],
                "action": action,
                "timestamp": int(time.time()),
                "source": "ai_autonomous",
            }
            try:
                await handle_signal(payload)
            except Exception:  # pragma: no cover - defensive
                LOGGER.exception("Autonomous AI failed to handle signal: %s", payload)

        await asyncio.sleep(interval)
