"""Telegram command handlers for autonomous AI trading."""
from __future__ import annotations

from typing import Optional

from telegram import Update
from telegram.ext import ContextTypes

from tvtelegrambingx.config_store import ConfigStore

CONFIG = ConfigStore()


def _parse_toggle(value: Optional[str]) -> Optional[bool]:
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized in {"on", "enable", "enabled", "true", "1"}:
        return True
    if normalized in {"off", "disable", "disabled", "false", "0"}:
        return False
    return None


def _parse_universe(raw_value: str) -> list[str]:
    universe: list[str] = []
    for part in raw_value.replace(";", ",").replace("|", ",").split(","):
        trimmed = part.strip()
        if trimmed:
            universe.append(trimmed.upper())
    return universe


async def cmd_ai_universe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None:
        return

    args = context.args or []
    if not args:
        universe = CONFIG.get_ai_universe()
        universe_text = ", ".join(universe) if universe else "alle"
        await message.reply_text(f"AI Universe: {universe_text}")
        return

    raw_value = " ".join(args)
    if raw_value.strip().lower() in {"clear", "reset", "off"}:
        CONFIG.set_global(ai_universe=[])
        await message.reply_text("OK. AI Universe zurückgesetzt (alle Assets).")
        return

    universe = _parse_universe(raw_value)
    if not universe:
        await message.reply_text("Nutzung: /ai_universe BTC-USDT,ETH-USDT")
        return

    CONFIG.set_global(ai_universe=universe)
    await message.reply_text(f"OK. AI Universe = {', '.join(universe)}")


async def cmd_ai_autonomous(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None:
        return

    args = context.args or []
    if not args:
        enabled = CONFIG.get_ai_autonomous_enabled()
        await message.reply_text(f"AI Autonom: {'ON' if enabled else 'OFF'}")
        return

    toggled = _parse_toggle(args[0])
    if toggled is None:
        await message.reply_text("Nutzung: /ai_autonomous on|off")
        return

    CONFIG.set_global(ai_autonomous_enabled=toggled)
    await message.reply_text(f"OK. AI Autonom {'ON' if toggled else 'OFF'}.")


async def cmd_ai_autonomous_interval(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None:
        return

    args = context.args or []
    if not args:
        interval = CONFIG.get_ai_autonomous_interval_seconds()
        if interval is None:
            await message.reply_text("AI Autonom Intervall: (ENV)")
        else:
            await message.reply_text(f"AI Autonom Intervall: {interval}s")
        return

    try:
        interval = int(args[0])
        if interval <= 0:
            raise ValueError
    except (TypeError, ValueError):
        await message.reply_text("Nutzung: /ai_autonomous_interval <Sekunden>")
        return

    CONFIG.set_global(ai_autonomous_interval_seconds=interval)
    await message.reply_text(f"OK. AI Autonom Intervall = {interval}s.")

async def cmd_ai_autonomous_dry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None:
        return

    args = context.args or []
    if not args:
        enabled = CONFIG.get_ai_autonomous_dry_run()
        await message.reply_text(f"AI Autonom Dry: {'ON' if enabled else 'OFF'}")
        return

    toggled = _parse_toggle(args[0])
    if toggled is None:
        await message.reply_text("Nutzung: /ai_autonomous_dry on|off")
        return

    CONFIG.set_global(ai_autonomous_dry_run=toggled)
    await message.reply_text(f"OK. AI Autonom Dry {'ON' if toggled else 'OFF'}.")


async def cmd_ai_autonomous_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None:
        return

    stats = CONFIG.get_ai_autonomous_stats()
    enabled = CONFIG.get_ai_autonomous_enabled()
    dry = CONFIG.get_ai_autonomous_dry_run()
    interval = CONFIG.get_ai_autonomous_interval_seconds()
    rsi_enabled = CONFIG.get_ai_filter_rsi_enabled()
    atr_enabled = CONFIG.get_ai_filter_atr_enabled()
    trend_enabled = CONFIG.get_ai_filter_trend_enabled()
    lines = [
        "<b>🤖 AI Autonom Status</b>",
        f"Aktiv: <code>{'ON' if enabled else 'OFF'}</code>",
        f"Dry-Run: <code>{'ON' if dry else 'OFF'}</code>",
        f"RSI Filter: <code>{'ON' if rsi_enabled else 'OFF'}</code>",
        f"ATR Filter: <code>{'ON' if atr_enabled else 'OFF'}</code>",
        f"Trend Filter: <code>{'ON' if trend_enabled else 'OFF'}</code>",
    ]
    if interval is not None:
        lines.append(f"Intervall: <code>{interval}s</code>")
    if stats:
        lines.append("<b>Statistik</b>")
        for key, value in stats.items():
            lines.append(f"• {key}: <code>{value}</code>")
    await message.reply_text("\n".join(lines), parse_mode="HTML")


async def cmd_ai_filter_rsi(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None:
        return

    args = context.args or []
    if not args:
        enabled = CONFIG.get_ai_filter_rsi_enabled()
        overbought = CONFIG.get_ai_filter_rsi_overbought()
        oversold = CONFIG.get_ai_filter_rsi_oversold()
        await message.reply_text(
            f"RSI Filter: {'ON' if enabled else 'OFF'} (OB {overbought}, OS {oversold})"
        )
        return

    if args[0].lower() in {"on", "off"}:
        toggled = _parse_toggle(args[0])
        if toggled is None:
            await message.reply_text("Nutzung: /ai_filter_rsi on|off|<overbought> <oversold>")
            return
        CONFIG.set_global(ai_filter_rsi_enabled=toggled)
        await message.reply_text(f"OK. RSI Filter {'ON' if toggled else 'OFF'}.")
        return

    if len(args) < 2:
        await message.reply_text("Nutzung: /ai_filter_rsi <overbought> <oversold>")
        return

    try:
        overbought = float(args[0])
        oversold = float(args[1])
    except (TypeError, ValueError):
        await message.reply_text("Nutzung: /ai_filter_rsi <overbought> <oversold>")
        return

    CONFIG.set_global(ai_filter_rsi_overbought=overbought, ai_filter_rsi_oversold=oversold)
    await message.reply_text(f"OK. RSI Filter OB={overbought} OS={oversold}.")


async def cmd_ai_filter_atr(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None:
        return

    args = context.args or []
    if not args:
        enabled = CONFIG.get_ai_filter_atr_enabled()
        minimum = CONFIG.get_ai_filter_atr_min_percent()
        await message.reply_text(
            f"ATR Filter: {'ON' if enabled else 'OFF'} (Min {minimum}%)"
        )
        return

    if args[0].lower() in {"on", "off"}:
        toggled = _parse_toggle(args[0])
        if toggled is None:
            await message.reply_text("Nutzung: /ai_filter_atr on|off|<min_percent>")
            return
        CONFIG.set_global(ai_filter_atr_enabled=toggled)
        await message.reply_text(f"OK. ATR Filter {'ON' if toggled else 'OFF'}.")
        return

    try:
        minimum = float(args[0])
    except (TypeError, ValueError):
        await message.reply_text("Nutzung: /ai_filter_atr <min_percent>")
        return

    CONFIG.set_global(ai_filter_atr_min_percent=minimum)
    await message.reply_text(f"OK. ATR Min = {minimum}%.")


async def cmd_ai_filter_trend(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None:
        return

    args = context.args or []
    if not args:
        enabled = CONFIG.get_ai_filter_trend_enabled()
        await message.reply_text(f"Trend Filter: {'ON' if enabled else 'OFF'}")
        return

    toggled = _parse_toggle(args[0])
    if toggled is None:
        await message.reply_text("Nutzung: /ai_filter_trend on|off")
        return

    CONFIG.set_global(ai_filter_trend_enabled=toggled)
    await message.reply_text(f"OK. Trend Filter {'ON' if toggled else 'OFF'}.")
