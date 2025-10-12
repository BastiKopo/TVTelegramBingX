"""Telegram bot handling auto-trade toggles and manual execution."""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional, Tuple

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

from tvtelegrambingx.bot.trade_executor import configure_store as configure_trade_store
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
LAST_SIGNAL_QUANTITIES: Dict[str, float] = {}
CONFIG: ConfigStore = ConfigStore()


def configure(settings: Settings) -> None:
    """Initialise global settings and bot instance."""
    global SETTINGS, BOT, LAST_SIGNAL_QUANTITIES
    SETTINGS = settings
    BOT = Bot(token=settings.telegram_bot_token)
    LAST_SIGNAL_QUANTITIES = {}
    configure_trade_store(CONFIG)


def _menu_text() -> str:
    return (
        "📋 *Menü*\n"
        "/start – Status & Infos\n"
        "/menu – Diese Übersicht\n"
        "/auto – Auto-Trade *an*\n"
        "/manual – Auto-Trade *aus*\n"
        "/botstart – Bot *Start* (Signale annehmen)\n"
        "/botstop – Bot *Stop* (Signale ignorieren)\n"
        "/status – PnL & Trading-Setup\n"
        "/mode <modus> – Handelsmodus setzen\n"
        "/margin [symbol] <USDT> – Margin konfigurieren\n"
        "/leverage [symbol] <x> – Hebel konfigurieren\n"
    )


def _global_config_overview() -> str:
    data = CONFIG.get()
    global_cfg = data.get("_global", {})
    margin_value = global_cfg.get("margin_usdt")
    margin_text = f"{margin_value} USDT" if margin_value is not None else "nicht gesetzt"
    leverage_value = global_cfg.get("leverage", 1)
    return (
        f"Mode: {global_cfg.get('mode', 'button')} | "
        f"Margin: {margin_text} | "
        f"Leverage: x{leverage_value}"
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a welcome message with current state."""
    global BOT_ENABLED, AUTO_TRADE

    message = update.effective_message
    if message is None:
        return

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


async def set_auto(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Enable auto trading."""
    global AUTO_TRADE
    AUTO_TRADE = True
    message = update.effective_message
    if message is not None:
        await message.reply_text("✅ Auto-Trade aktiviert.")


async def set_manual(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Disable auto trading."""
    global AUTO_TRADE
    AUTO_TRADE = False
    message = update.effective_message
    if message is not None:
        await message.reply_text("❎ Manueller Modus aktiviert.")


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
    margin_value = config_data.get("margin_usdt")
    margin_text = f"{margin_value} USDT" if margin_value is not None else "nicht gesetzt"
    leverage_value = config_data.get("leverage", 1)
    status_text = (
        f"{summary}\n\n"
        "⚙️ *Trading-Konfiguration*\n"
        f"Mode: {config_data.get('mode', 'button')}\n"
        f"Margin: {margin_text}\n"
        f"Leverage: x{leverage_value}"
    )
    await message.reply_text(status_text, parse_mode="Markdown")


def _parse_symbol_and_value(args: Tuple[str, ...]) -> Tuple[Optional[str], Optional[str]]:
    if not args:
        return None, None
    if len(args) == 1:
        return None, args[0]
    return args[0], args[1]


async def mode_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None:
        return
    if not context.args:
        await message.reply_text("Nutzung: /mode button")
        return

    mode_value = context.args[0].lower()
    CONFIG.set_global(mode=mode_value)
    await message.reply_text(f"Mode gesetzt: {mode_value}")


async def margin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None:
        return

    symbol, value = _parse_symbol_and_value(tuple(context.args))
    if value is None:
        await message.reply_text("Nutzung: /margin [symbol] <USDT>")
        return

    try:
        amount = float(value)
    except ValueError:
        await message.reply_text("Ungültiger Wert.")
        return

    if amount <= 0:
        await message.reply_text("Margin muss größer als 0 sein.")
        return

    if symbol:
        CONFIG.set_symbol(symbol, margin_usdt=amount)
        await message.reply_text(f"Margin für {symbol.upper()}: {amount} USDT")
    else:
        CONFIG.set_global(margin_usdt=amount)
        await message.reply_text(f"Margin global: {amount} USDT")


async def leverage_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if message is None:
        return

    symbol, value = _parse_symbol_and_value(tuple(context.args))
    if value is None:
        await message.reply_text("Nutzung: /leverage [symbol] <x>")
        return

    try:
        leverage = int(float(value))
    except ValueError:
        await message.reply_text("Ungültiger Wert.")
        return

    if leverage <= 0:
        await message.reply_text("Hebel muss größer als 0 sein.")
        return

    if symbol:
        CONFIG.set_symbol(symbol, leverage=leverage)
        await message.reply_text(f"Leverage für {symbol.upper()}: x{leverage}")
    else:
        CONFIG.set_global(leverage=leverage)
        await message.reply_text(f"Leverage global: x{leverage}")


def _parse_quantity(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None

    try:
        quantity = float(value)
    except (TypeError, ValueError):
        LOGGER.warning("Invalid quantity received from signal: %s", value)
        return None

    if quantity <= 0:
        LOGGER.warning("Non-positive quantity received from signal: %s", value)
        return None

    return quantity


async def _send_signal_message(symbol: str, action: str, quantity: Optional[float]) -> None:
    assert SETTINGS is not None

    bot = APPLICATION.bot if APPLICATION is not None else BOT
    if bot is None:
        LOGGER.error("No Telegram bot available to send messages")
        return

    text = (
        "📊 *Signal*\n"
        f"Asset: `{symbol}`\n"
        f"Aktion: `{action}`\n"
        f"Auto-Trade: {'🟢 On' if AUTO_TRADE else '🔴 Off'}"
    )

    if quantity is not None:
        text += f"\nMenge: `{quantity}`"
    elif SETTINGS.bingx_default_quantity is not None:
        text += f"\nMenge: `{SETTINGS.bingx_default_quantity}` (Standard)"

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

    markup = InlineKeyboardMarkup(buttons)
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

    LOGGER.info("Received signal: symbol=%s action=%s auto=%s", symbol, action, AUTO_TRADE)

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

    quantity = _parse_quantity(
        payload.get("quantity") or payload.get("qty") or payload.get("size")
    )
    if quantity is not None:
        LAST_SIGNAL_QUANTITIES[symbol] = quantity

    await _send_signal_message(symbol, action, quantity)

    already_executed = bool(payload.get("executed"))

    if AUTO_TRADE and not already_executed:
        try:
            executed = await execute_trade(symbol=symbol, action=action, quantity=quantity)
        except Exception as exc:  # pragma: no cover - requires BingX failure scenarios
            LOGGER.exception("Auto trade failed: symbol=%s action=%s", symbol, action)
            return
        if executed is not None:
            LAST_SIGNAL_QUANTITIES[symbol] = executed


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

    quantity = LAST_SIGNAL_QUANTITIES.get(symbol)

    try:
        executed = await execute_trade(symbol=symbol, action=action, quantity=quantity)
        if executed is not None:
            LAST_SIGNAL_QUANTITIES[symbol] = executed
    except Exception as exc:  # pragma: no cover - requires BingX failure scenarios
        LOGGER.exception("Manual trade failed: symbol=%s action=%s", symbol, action)
        await query.edit_message_text(f"⚠️ Trade fehlgeschlagen: {exc}")
        return

    quantity_text = f" Menge: {executed}" if executed is not None else ""
    await query.edit_message_text(f"✅ Manueller Trade ausgeführt: {symbol} {action}{quantity_text}")


def build_application(settings: Settings) -> Application:
    """Create the Telegram application and register handlers."""
    application = ApplicationBuilder().token(settings.telegram_bot_token).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("menu", menu_cmd))
    application.add_handler(CommandHandler("auto", set_auto))
    application.add_handler(CommandHandler("manual", set_manual))
    application.add_handler(CommandHandler("botstart", bot_start))
    application.add_handler(CommandHandler("botstop", bot_stop))
    application.add_handler(CommandHandler("status", status_cmd))
    application.add_handler(CommandHandler("mode", mode_cmd))
    application.add_handler(CommandHandler("margin", margin_cmd))
    application.add_handler(CommandHandler("leverage", leverage_cmd))
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
