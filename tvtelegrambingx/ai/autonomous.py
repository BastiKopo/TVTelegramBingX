"""Autonomous AI trading loop based on simple candlestick signals."""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Iterable, Optional

from tvtelegrambingx.config import Settings
from tvtelegrambingx.config_store import ConfigStore
from tvtelegrambingx.integrations import bingx_account
from telegram.constants import ParseMode

LOGGER = logging.getLogger(__name__)
CONFIG = ConfigStore()


def configure_ai(settings: Settings) -> None:
    """No-op configurator for autonomous AI."""
    CONFIG.record_ai_autonomous_stat("configured_at", int(time.time()))


async def _send_dry_run_message(*, bot, chat_id: Optional[str], text: str) -> None:
    if bot is None or chat_id is None:
        return
    try:
        await bot.send_message(chat_id=chat_id, text=text, parse_mode=ParseMode.HTML)
    except Exception:  # pragma: no cover - network/telegram issues
        LOGGER.debug("Failed to send dry-run message", exc_info=True)


def _sma(values: list[float]) -> Optional[float]:
    if not values:
        return None
    return sum(values) / len(values)


def _ema(values: list[float], period: int) -> Optional[float]:
    if len(values) < period:
        return None
    multiplier = 2 / (period + 1)
    ema_value = sum(values[:period]) / period
    for price in values[period:]:
        ema_value = (price - ema_value) * multiplier + ema_value
    return ema_value


def _rsi(values: list[float], period: int = 14) -> Optional[float]:
    if len(values) <= period:
        return None
    gains = 0.0
    losses = 0.0
    for i in range(-period, 0):
        delta = values[i] - values[i - 1]
        if delta >= 0:
            gains += delta
        else:
            losses -= delta
    if losses == 0:
        return 100.0
    rs = gains / losses
    return 100 - (100 / (1 + rs))


def _atr_percent(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> Optional[float]:
    if len(closes) <= period:
        return None
    trs = []
    for i in range(-period, 0):
        high = highs[i]
        low = lows[i]
        prev_close = closes[i - 1]
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        trs.append(tr)
    atr = sum(trs) / len(trs) if trs else 0.0
    last_close = closes[-1]
    if last_close == 0:
        return None
    return (atr / last_close) * 100


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
    rsi_overbought: float,
    rsi_oversold: float,
    atr_min_percent: float,
    rsi_enabled: bool,
    atr_enabled: bool,
    trend_enabled: bool,
) -> tuple[Optional[str], Optional[str]]:
    klines = await bingx_account.get_klines(symbol, interval=interval, limit=limit)
    closes = [float(entry["close"]) for entry in klines if "close" in entry]
    highs = [float(entry["high"]) for entry in klines if "high" in entry]
    lows = [float(entry["low"]) for entry in klines if "low" in entry]
    if len(closes) < 21:
        return None, None

    short = _sma(closes[-5:])
    long = _sma(closes[-20:])
    prev_short = _sma(closes[-6:-1])
    prev_long = _sma(closes[-21:-1])
    if short is None or long is None or prev_short is None or prev_long is None:
        return None, None

    if prev_short <= prev_long and short > long:
        action = "LONG_BUY"
    elif prev_short >= prev_long and short < long:
        action = "SHORT_SELL"
    else:
        action = None

    if action is None:
        return None, None

    if rsi_enabled:
        rsi_value = _rsi(closes)
        if rsi_value is None:
            return None, "rsi_unavailable"
        if action == "LONG_BUY" and rsi_value > rsi_overbought:
            return None, "rsi_overbought"
        if action == "SHORT_SELL" and rsi_value < rsi_oversold:
            return None, "rsi_oversold"

    if atr_enabled:
        atr_percent = _atr_percent(highs, lows, closes)
        if atr_percent is None:
            return None, "atr_unavailable"
        if atr_percent < atr_min_percent:
            return None, "atr_too_low"

    if trend_enabled:
        ema_200 = _ema(closes, 200)
        if ema_200 is None:
            return None, "ema_unavailable"
        last_close = closes[-1]
        if action == "LONG_BUY" and last_close < ema_200:
            return None, "trend_below_ema"
        if action == "SHORT_SELL" and last_close > ema_200:
            return None, "trend_above_ema"

    return action, None


async def run_ai_autonomous(settings: Settings) -> None:
    """Run autonomous AI trading loop."""
    from tvtelegrambingx.bot.telegram_bot import handle_signal
    from tvtelegrambingx.bot.telegram_bot import APPLICATION, BOT, SETTINGS as BOT_SETTINGS

    while True:
        interval = CONFIG.get_ai_autonomous_interval_seconds()
        if interval is None:
            interval = settings.ai_autonomous_interval_seconds
        interval = max(10, interval)

        enabled = CONFIG.get().get("_global", {}).get("ai_autonomous_enabled")
        if enabled is None:
            enabled = settings.ai_autonomous_enabled
        dry_run = CONFIG.get().get("_global", {}).get("ai_autonomous_dry_run")
        if dry_run is None:
            dry_run = settings.ai_autonomous_dry_run

        rsi_enabled = CONFIG.get().get("_global", {}).get("ai_filter_rsi_enabled")
        if rsi_enabled is None:
            rsi_enabled = settings.ai_filter_rsi_enabled
        atr_enabled = CONFIG.get().get("_global", {}).get("ai_filter_atr_enabled")
        if atr_enabled is None:
            atr_enabled = settings.ai_filter_atr_enabled
        trend_enabled = CONFIG.get().get("_global", {}).get("ai_filter_trend_enabled")
        if trend_enabled is None:
            trend_enabled = settings.ai_filter_trend_enabled
        rsi_overbought = CONFIG.get_ai_filter_rsi_overbought()
        if rsi_overbought is None:
            rsi_overbought = settings.ai_filter_rsi_overbought
        rsi_oversold = CONFIG.get_ai_filter_rsi_oversold()
        if rsi_oversold is None:
            rsi_oversold = settings.ai_filter_rsi_oversold
        atr_min_percent = CONFIG.get_ai_filter_atr_min_percent()
        if atr_min_percent is None:
            atr_min_percent = settings.ai_filter_atr_min_percent

        if not enabled:
            await asyncio.sleep(interval)
            continue

        universe = CONFIG.get_ai_universe()
        if not universe:
            LOGGER.warning("AI autonomous mode enabled but universe is empty")
            CONFIG.increment_ai_autonomous_stat("skipped_empty_universe")
            await asyncio.sleep(interval)
            continue

        try:
            positions = await bingx_account.get_positions()
        except Exception:  # pragma: no cover - network/credentials
            LOGGER.exception("Failed to fetch positions for autonomous AI")
            CONFIG.increment_ai_autonomous_stat("errors_positions")
            positions = []

        for symbol in universe:
            try:
                action, blocked_reason = await _evaluate_symbol(
                    symbol,
                    interval=settings.ai_autonomous_kline_interval,
                    limit=settings.ai_autonomous_kline_limit,
                    rsi_overbought=rsi_overbought,
                    rsi_oversold=rsi_oversold,
                    atr_min_percent=atr_min_percent,
                    rsi_enabled=bool(rsi_enabled),
                    atr_enabled=bool(atr_enabled),
                    trend_enabled=bool(trend_enabled),
                )
            except Exception:  # pragma: no cover - network/invalid symbol
                LOGGER.exception("Failed to evaluate symbol for autonomous AI: %s", symbol)
                CONFIG.increment_ai_autonomous_stat("errors_eval")
                continue

            if action is None:
                if blocked_reason:
                    CONFIG.increment_ai_autonomous_stat(f"filtered_{blocked_reason}")
                    if dry_run:
                        await _send_dry_run_message(
                            bot=APPLICATION.bot if APPLICATION is not None else BOT,
                            chat_id=BOT_SETTINGS.telegram_chat_id if BOT_SETTINGS is not None else None,
                            text=(
                                f"🤖 AI Autonom (Dry-Run): {symbol} blockiert "
                                f"({blocked_reason})."
                            ),
                        )
                else:
                    CONFIG.increment_ai_autonomous_stat("no_signal")
                continue
            if _has_open_position(positions, symbol, action):
                CONFIG.increment_ai_autonomous_stat("skipped_open_position")
                continue

            CONFIG.increment_ai_autonomous_stat("signals_generated")
            CONFIG.record_ai_autonomous_stat("last_symbol", symbol)
            CONFIG.record_ai_autonomous_stat("last_action", action)
            CONFIG.record_ai_autonomous_stat("last_timestamp", int(time.time()))

            payload = {
                "symbol": symbol,
                "actions": [action],
                "action": action,
                "timestamp": int(time.time()),
                "source": "ai_autonomous",
            }
            try:
                if dry_run:
                    CONFIG.increment_ai_autonomous_stat("signals_dry_run")
                    await _send_dry_run_message(
                        bot=APPLICATION.bot if APPLICATION is not None else BOT,
                        chat_id=BOT_SETTINGS.telegram_chat_id if BOT_SETTINGS is not None else None,
                        text=(
                            f"🤖 AI Autonom (Dry-Run): {symbol} -> {action} "
                            f"(SMA 5/20)."
                        ),
                    )
                else:
                    await handle_signal(payload)
                    CONFIG.increment_ai_autonomous_stat("signals_dispatched")
            except Exception:  # pragma: no cover - defensive
                LOGGER.exception("Autonomous AI failed to handle signal: %s", payload)
                CONFIG.increment_ai_autonomous_stat("errors_dispatch")

        await asyncio.sleep(interval)
