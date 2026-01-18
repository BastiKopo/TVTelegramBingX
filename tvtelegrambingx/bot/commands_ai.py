"""Telegram command handlers for the AI gatekeeper."""
from __future__ import annotations

from typing import Optional

from telegram import Update
from telegram.ext import ContextTypes

from tvtelegrambingx.ai.gatekeeper import ai_status_text, record_feedback
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


async def cmd_ai(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None:
        return

    args = context.args or []
    if not args:
        enabled = CONFIG.get_ai_enabled()
        await message.reply_text(f"AI Gatekeeper: {'ON' if enabled else 'OFF'}")
        return

    toggled = _parse_toggle(args[0])
    if toggled is None:
        await message.reply_text("Nutzung: /ai on|off")
        return

    CONFIG.set_global(ai_enabled=toggled)
    await message.reply_text(f"OK. AI Gatekeeper {'ON' if toggled else 'OFF'}.")


async def cmd_ai_mode(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None:
        return

    args = context.args or []
    if not args:
        mode = CONFIG.get_ai_mode()
        await message.reply_text(f"AI Modus: {mode}")
        return

    mode = args[0].strip().lower()
    if mode not in {"gatekeeper", "shadow", "off", "advanced", "autonomous"}:
        await message.reply_text("Nutzung: /ai_mode gatekeeper|shadow|off|advanced|autonomous")
        return

    CONFIG.set_global(ai_mode=mode)
    await message.reply_text(f"OK. AI Modus = {mode}.")


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


async def cmd_ai_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None:
        return

    args = context.args or []
    symbol = args[0].upper() if args else None
    await message.reply_text(ai_status_text(symbol), parse_mode="HTML")


async def cmd_ai_feedback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None:
        return

    args = context.args or []
    if len(args) < 3:
        await message.reply_text("Nutzung: /ai_feedback <SYMBOL> <ACTION> <win|loss>")
        return

    symbol = args[0].upper()
    action = args[1].upper()
    outcome = args[2].strip().lower()
    if outcome not in {"win", "loss"}:
        await message.reply_text("Outcome muss win oder loss sein.")
        return

    win_rate = record_feedback(symbol, action, outcome)
    await message.reply_text(
        f"Feedback gespeichert. {symbol} {action} Win-Rate: {win_rate:.2f}"
    )
