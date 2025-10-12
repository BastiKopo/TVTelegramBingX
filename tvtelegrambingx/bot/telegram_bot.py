"""Telegram bot handling auto-trade toggles and manual execution."""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (Application, ApplicationBuilder, CallbackQueryHandler,
                          CommandHandler, ContextTypes)

from tvtelegrambingx.bot.trade_executor import execute_trade
from tvtelegrambingx.config import Settings

LOGGER = logging.getLogger(__name__)

AUTO_TRADE = False
APPLICATION: Optional[Application] = None
SETTINGS: Optional[Settings] = None
BOT: Optional[Bot] = None


def configure(settings: Settings) -> None:
    """Initialise global settings and bot instance."""
    global SETTINGS, BOT
    SETTINGS = settings
    BOT = Bot(token=settings.telegram_bot_token)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a welcome message."""
    await update.message.reply_text(
        "🤖 TVTelegramBingX Bot gestartet.\nNutze /auto oder /manual um den Modus zu wechseln."
    )


async def set_auto(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Enable auto trading."""
    global AUTO_TRADE
    AUTO_TRADE = True
    await update.message.reply_text("✅ Auto-Trade aktiviert.")


async def set_manual(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Disable auto trading."""
    global AUTO_TRADE
    AUTO_TRADE = False
    await update.message.reply_text("❎ Manueller Modus aktiviert.")


async def _send_signal_message(symbol: str, action: str) -> None:
    assert SETTINGS is not None

    bot = APPLICATION.bot if APPLICATION is not None else BOT
    if bot is None:
        LOGGER.error("No Telegram bot available to send messages")
        return

    text = (
        "📊 SIGNAL\n"
        f"Asset: {symbol}\n"
        f"Aktion: {action}\n"
        f"Auto-Trade: {'On' if AUTO_TRADE else 'Off'}"
    )

    buttons = [
        [
            InlineKeyboardButton("🟢 Long öffnen", callback_data=f"LONG_BUY:{symbol}"),
            InlineKeyboardButton("⚪️ Long schließen", callback_data=f"LONG_SELL:{symbol}"),
        ],
        [
            InlineKeyboardButton("🔴 Short öffnen", callback_data=f"SHORT_SELL:{symbol}"),
            InlineKeyboardButton("⚫️ Short schließen", callback_data=f"SHORT_BUY:{symbol}"),
        ],
    ]

    markup = InlineKeyboardMarkup(buttons)
    await bot.send_message(chat_id=SETTINGS.telegram_chat_id, text=text, reply_markup=markup)


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

    LOGGER.info("Received signal: symbol=%s action=%s auto=%s", symbol, action, AUTO_TRADE)
    await _send_signal_message(symbol, action)

    if AUTO_TRADE:
        await execute_trade(symbol=symbol, action=action)


async def on_button_click(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle inline keyboard button presses."""
    query = update.callback_query
    if query is None or query.data is None:
        return

    await query.answer()
    try:
        action, symbol = query.data.split(":", 1)
    except ValueError:
        LOGGER.warning("Malformed callback data: %s", query.data)
        return

    await execute_trade(symbol=symbol, action=action)
    await query.edit_message_text(f"✅ Manueller Trade ausgeführt: {symbol} {action}")


def build_application(settings: Settings) -> Application:
    """Create the Telegram application and register handlers."""
    application = ApplicationBuilder().token(settings.telegram_bot_token).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("auto", set_auto))
    application.add_handler(CommandHandler("manual", set_manual))
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
        await APPLICATION.updater.start_polling()
        await APPLICATION.updater.wait()
    finally:
        await APPLICATION.updater.stop()
        await APPLICATION.stop()
        await APPLICATION.shutdown()
