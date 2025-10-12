"""Telegram bot handling auto-trade toggles and manual execution."""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from tvtelegrambingx.bot.trade_executor import execute_trade
from tvtelegrambingx.config import Settings
from tvtelegrambingx.config_store import ConfigStore
from tvtelegrambingx.integrations.bingx_account import get_status_summary

LOGGER = logging.getLogger(__name__)

AUTO_TRADE = False
BOT_ENABLED = True
APPLICATION: Optional[Application] = None
SETTINGS: Optional[Settings] = None
BOT: Optional[Bot] = None
CONFIG: ConfigStore = ConfigStore()


def configure(settings: Settings) -> None:
    """Initialise global settings and bot instance."""
    global SETTINGS, BOT
    SETTINGS = settings
    BOT = Bot(token=settings.telegram_bot_token)
    _refresh_auto_trade_cache()


def _refresh_auto_trade_cache() -> None:
    global AUTO_TRADE
    AUTO_TRADE = CONFIG.get_auto_trade()


def _menu_text() -> str:
    return (
        "📋 *Menü*\n"
        "/start – Status & Infos\n"
        "/menu – Diese Übersicht\n"
        "/auto on|off – Auto-Trade global schalten\n"
        "/auto_<symbol> on|off – Auto-Trade für Symbol\n"
        "/manual – Auto-Trade aus (Alias)\n"
        "/botstart – Bot *Start* (Signale annehmen)\n"
        "/botstop – Bot *Stop* (Signale ignorieren)\n"
        "/status – PnL & Trading-Setup"
    )


def _global_config_overview() -> str:
    data = CONFIG.get()
    global_cfg = data.get("_global", {})
    auto_text = "🟢 Auto" if global_cfg.get("auto_trade") else "🔴 Auto aus"
    return f"{auto_text}"


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a welcome message with current state."""
    message = update.effective_message
    if message is None:
        return

    _refresh_auto_trade_cache()

    status_line = (
        "🤖 TVTelegramBingX bereit.\n"
        f"Bot: {'🟢 Aktiv' if BOT_ENABLED else '🔴 Gestoppt'} | "
        f"Auto: {'🟢 An' if AUTO_TRADE else '🔴 Aus'}\n"
        f"{_global_config_overview()}\n\n"
    )
    await message.reply_text(status_line + _menu_text(), parse_mode="Markdown")


async def menu_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Display the command overview."""
    message = update.effective_message
    if message is None:
        return
    await message.reply_text(_menu_text(), parse_mode="Markdown")


async def set_manual(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Disable auto trading."""
    CONFIG.set_global(auto_trade=False)
    _refresh_auto_trade_cache()
    message = update.effective_message
    if message is not None:
        await message.reply_text("❎ Manueller Modus aktiviert.")


async def auto_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Toggle auto trading globally or per symbol."""

    message = update.effective_message
    if message is None:
        return

    text = (message.text or "").strip()

    if text.startswith("/auto_"):
        try:
            command_part, arg_part = text.split(None, 1)
        except ValueError:
            await message.reply_text("Nutzung: /auto_<SYMBOL> on|off")
            return

        symbol_key = command_part.split("@", 1)[0].replace("/auto_", "").upper()
        value = arg_part.strip().lower()
        enabled = value in {"on", "ein", "true", "1"}
        CONFIG.set_symbol(symbol_key, auto_trade=enabled)
        await message.reply_text(
            f"Auto-Trade für {symbol_key}: {'ON' if enabled else 'OFF'}"
        )
        return

    if not context.args:
        await message.reply_text("Nutzung: /auto on|off")
        return

    value = context.args[0].lower()
    enabled = value in {"on", "ein", "true", "1"}
    CONFIG.set_global(auto_trade=enabled)
    _refresh_auto_trade_cache()
    await message.reply_text(f"Auto-Trade global: {'ON' if enabled else 'OFF'}")


async def bot_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Enable processing of incoming signals."""
    global BOT_ENABLED
    BOT_ENABLED = True
    message = update.effective_message
    if message is not None:
        await message.reply_text("🟢 Bot gestartet – Signale werden angenommen.")


async def bot_stop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Disable processing of incoming signals."""
    global BOT_ENABLED
    BOT_ENABLED = False
    message = update.effective_message
    if message is not None:
        await message.reply_text("🔴 Bot gestoppt – eingehende Signale werden ignoriert.")


async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Report aggregated PnL and open positions."""
    message = update.effective_message
    if message is None:
        return

    try:
        summary = await get_status_summary()
    except Exception:  # pragma: no cover - defensive logging
        LOGGER.exception("Failed to load BingX status summary")
        await message.reply_text("⚠️ Status konnte nicht abgerufen werden.")
        return

    config_data = CONFIG.get().get("_global", {})
    auto_text = "ON" if config_data.get("auto_trade") else "OFF"
    status_text = (
        f"{summary}\n\n"
        "⚙️ *Trading-Konfiguration*\n"
        f"AutoTrade: {auto_text}"
    )
    await message.reply_text(status_text, parse_mode="Markdown")


def _build_signal_buttons(symbol: str) -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton("🟢 Long öffnen", callback_data=f"LONG_BUY_{symbol}"),
            InlineKeyboardButton("⚪️ Long schließen", callback_data=f"LONG_SELL_{symbol}"),
        ],
        [
            InlineKeyboardButton("🔴 Short öffnen", callback_data=f"SHORT_SELL_{symbol}"),
            InlineKeyboardButton("⚫️ Short schließen", callback_data=f"SHORT_BUY_{symbol}"),
        ],
    ]
    return InlineKeyboardMarkup(buttons)


async def _send_signal_message(symbol: str, action: str, auto_enabled: bool) -> None:
    assert SETTINGS is not None

    bot = APPLICATION.bot if APPLICATION is not None else BOT
    if bot is None:
        LOGGER.error("No Telegram bot available to send messages")
        return

    text = (
        "📊 *Signal*\n"
        f"Asset: `{symbol}`\n"
        f"Aktion: `{action}`\n"
        f"Auto-Trade: {'🟢 On' if auto_enabled else '🔴 Off'}"
    )

    markup = _build_signal_buttons(symbol)
    await bot.send_message(
        chat_id=SETTINGS.telegram_chat_id,
        text=text,
        reply_markup=markup,
        parse_mode="Markdown",
    )


async def handle_signal(payload: Dict[str, Any]) -> None:
    """React to TradingView alerts."""
    if SETTINGS is None:
        LOGGER.error("Telegram bot not initialised; signal ignored")
        return

    symbol = payload.get("symbol")
    action = payload.get("action")
    if not symbol or not action:
        LOGGER.warning("Invalid payload: %s", payload)
        return

    auto_enabled = CONFIG.get_auto_trade(symbol)
    LOGGER.info(
        "Received signal: symbol=%s action=%s auto=%s",
        symbol,
        action,
        auto_enabled,
    )

    if not BOT_ENABLED:
        bot = APPLICATION.bot if APPLICATION is not None else BOT
        if bot is None:
            LOGGER.error("No Telegram bot available to send disabled notification")
            return
        await bot.send_message(
            chat_id=SETTINGS.telegram_chat_id,
            text=(
                "⏸ Signal empfangen, aber Bot ist gestoppt.\n"
                f"Asset: {symbol}\nAktion: {action}"
            ),
        )
        return

    await _send_signal_message(symbol, action, auto_enabled)

    already_executed = bool(payload.get("executed"))

    if auto_enabled and not already_executed:
        try:
            await execute_trade(symbol=symbol, action=action)
        except Exception as exc:  # pragma: no cover - requires BingX failure scenarios
            LOGGER.exception("Auto trade failed: symbol=%s action=%s", symbol, action)
            return


async def on_button_click(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle inline keyboard button presses."""
    query = update.callback_query
    if query is None or query.data is None:
        return

    await query.answer()
    try:
        parts = query.data.split("_")
    except AttributeError:
        LOGGER.warning("Malformed callback data: %s", query.data)
        return

    if len(parts) < 3:
        LOGGER.warning("Malformed callback data: %s", query.data)
        await query.edit_message_text("Fehlerhafte Aktion.")
        return

    action = "_".join(parts[:2])
    symbol = "_".join(parts[2:])

    if not BOT_ENABLED:
        await query.edit_message_text("🔴 Bot ist gestoppt – manuelle Trades sind deaktiviert.")
        return

    try:
        success = await execute_trade(symbol=symbol, action=action)
    except Exception as exc:  # pragma: no cover - requires BingX failure scenarios
        LOGGER.exception("Manual trade failed: symbol=%s action=%s", symbol, action)
        await query.edit_message_text(f"⚠️ Trade fehlgeschlagen: {exc}")
        return

    if success:
        await query.edit_message_text(f"✅ Manueller Trade ausgeführt: {symbol} {action}")
    else:
        await query.edit_message_text(f"⚠️ Aktion nicht ausgeführt: {symbol} {action}")


def build_application(settings: Settings) -> Application:
    """Create the Telegram application and register handlers."""
    application = ApplicationBuilder().token(settings.telegram_bot_token).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("menu", menu_cmd))
    application.add_handler(CommandHandler("auto", auto_cmd))
    application.add_handler(
        MessageHandler(filters.COMMAND & filters.Regex(r"^/auto_"), auto_cmd)
    )
    application.add_handler(CommandHandler("manual", set_manual))
    application.add_handler(CommandHandler("botstart", bot_start))
    application.add_handler(CommandHandler("botstop", bot_stop))
    application.add_handler(CommandHandler("status", status_cmd))
    application.add_handler(CallbackQueryHandler(on_button_click))
    return application


async def run_telegram_bot(settings: Settings) -> None:
    """Bootstrap and run the Telegram bot."""
    global APPLICATION, SETTINGS, BOT
    SETTINGS = settings
    APPLICATION = build_application(settings)
    BOT = APPLICATION.bot
    LOGGER.info("Starting Telegram bot polling")
    await APPLICATION.initialize()
    await APPLICATION.start()
    try:
        if APPLICATION.updater is None:
            LOGGER.error("Application has no updater; polling cannot start")
            return

        await APPLICATION.updater.start_polling()
        await asyncio.Future()
    except asyncio.CancelledError:
        LOGGER.info("Telegram bot task cancelled")
        raise
    finally:
        if APPLICATION.updater is not None:
            await APPLICATION.updater.stop()
        await APPLICATION.stop()
        await APPLICATION.shutdown()
