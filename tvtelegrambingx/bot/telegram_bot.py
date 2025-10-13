"""Telegram bot handling auto-trade toggles and manual execution."""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional

import html

from telegram import Bot, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from tvtelegrambingx.bot.commands_trade_settings import (
    cmd_leverage,
    cmd_margin,
    cmd_set,
)
from tvtelegrambingx.bot.trade_executor import execute_trade
from tvtelegrambingx.bot.user_prefs import get_global
from tvtelegrambingx.config import Settings
from tvtelegrambingx.config_store import ConfigStore
from tvtelegrambingx.integrations.bingx_account import get_status_summary

LOGGER = logging.getLogger(__name__)

_COMMAND_DEFINITIONS = (
    ("start", "Begrüßung & aktueller Status", "/start"),
    ("help", "Befehlsübersicht", "/help"),
    ("status", "PnL & Trading-Setup anzeigen", "/status"),
    ("auto", "Auto-Trade global schalten", "/auto on|off"),
    ("manual", "Auto-Trade deaktivieren (Alias)", "/manual"),
    ("botstart", "Bot starten (Signale annehmen)", "/botstart"),
    ("botstop", "Bot stoppen (Signale ignorieren)", "/botstop"),
    ("margin", "Globale Margin anzeigen/setzen", "/margin [USDT]"),
    ("leverage", "Globalen Leverage anzeigen/setzen", "/leverage [x]"),
    ("set", "Aktuelle globale Werte anzeigen", "/set"),
)

_ADDITIONAL_HELP_LINES = (
    (None, "Auto-Trade je Symbol", "/auto_<SYMBOL> on|off"),
)


def _safe_html(text: Any) -> str:
    """Return a HTML escaped representation for Telegram messages."""

    return html.escape("" if text is None else str(text), quote=True)

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


def _menu_text_html() -> str:
    lines = ["<b>📋 Befehle</b>"]
    for _, description, usage in _COMMAND_DEFINITIONS:
        lines.append(f"<code>{_safe_html(usage)}</code> – {_safe_html(description)}")
    for _, description, usage in _ADDITIONAL_HELP_LINES:
        lines.append(f"<code>{_safe_html(usage)}</code> – {_safe_html(description)}")
    return "\n".join(lines)


def _parse_chat_id(raw_chat_id: Any) -> Optional[int]:
    try:
        if raw_chat_id is None:
            return None
        return int(str(raw_chat_id))
    except (TypeError, ValueError):
        LOGGER.warning("Ungültige Chat-ID: %s", raw_chat_id)
        return None


def _format_margin(raw_value: Any) -> str:
    if raw_value in {None, ""}:
        return "2 USDT"
    try:
        return f"{float(raw_value):g} USDT"
    except (TypeError, ValueError):
        return str(raw_value)


def _format_leverage(raw_value: Any) -> str:
    if raw_value in {None, ""}:
        return "35x"
    try:
        return f"{int(raw_value)}x"
    except (TypeError, ValueError):
        return str(raw_value)


def _current_trade_settings(chat_id: Optional[int]) -> tuple[str, str]:
    prefs = get_global(chat_id) if chat_id is not None else {}
    margin_value = prefs.get("margin_usdt")
    leverage_value = prefs.get("leverage")
    return _format_margin(margin_value), _format_leverage(leverage_value)


def _format_symbol(symbol: str) -> str:
    cleaned = "".join(ch for ch in str(symbol) if ch.isalnum())
    if not cleaned:
        cleaned = str(symbol)
    return cleaned.upper()


def _direction_from_action(action: str) -> str:
    action_upper = str(action).upper()
    if "SHORT" in action_upper:
        return "SHORT"
    if "LONG" in action_upper:
        return "LONG"
    if "SELL" in action_upper:
        return "SHORT"
    if "BUY" in action_upper:
        return "LONG"
    return action_upper or "—"


def _startup_greeting_text(chat_id: Optional[int]) -> str:
    _refresh_auto_trade_cache()
    margin_text, leverage_text = _current_trade_settings(chat_id)

    auto_text = _safe_html("🟢" if AUTO_TRADE else "🔴")
    bot_text = _safe_html("🟢" if BOT_ENABLED else "🔴")
    symbol_display = _safe_html("LTCUSDT")
    auto_trade_text = _safe_html("🟢 On" if AUTO_TRADE else "🔴 Off")

    lines = [
        "🤖 TVTelegramBingX",
        "---------------------------------------",
        f"Bot ist Aktiv {bot_text} und im Autobetrieb: {auto_text}",
        "",
        "Bei Signale:",
        "",
        f"📊 Signal - {symbol_display}",
        "---------------------------------------",
        f"Margin: {_safe_html(margin_text)}",
        f"Leverage: {_safe_html(leverage_text)}",
        "Richtung: LONG oder SHORT (je nach Signal)",
        f"Auto-Trade: {auto_trade_text}",
    ]

    return "\n".join(lines)


async def _ensure_command_menu(bot: Bot) -> None:
    commands = [
        BotCommand(command=name, description=description)
        for name, description, _ in _COMMAND_DEFINITIONS
    ]
    await bot.set_my_commands(commands)


async def _reply_html(message, text: str):
    return await message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a welcome message with current state."""
    message = update.effective_message
    if message is None:
        return

    chat = update.effective_chat
    chat_id = _parse_chat_id(chat.id if chat is not None else None)
    text = _startup_greeting_text(chat_id)
    await _reply_html(message, text)


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Return only the command overview."""
    message = update.effective_message
    if message is None:
        return
    await _reply_html(message, _menu_text_html())


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
        f"{_safe_html(summary)}\n\n"
        "<b>⚙️ Trading-Konfiguration</b>\n"
        f"AutoTrade: <code>{_safe_html(auto_text)}</code>"
    )
    await _reply_html(message, status_text)


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

    try:
        chat_id = int(SETTINGS.telegram_chat_id)
    except (TypeError, ValueError):
        chat_id = None

    margin_text, leverage_text = _current_trade_settings(chat_id)
    direction_text = _direction_from_action(action)

    text = "\n".join(
        [
            f"📊 Signal - {_safe_html(_format_symbol(symbol))}",
            "---------------------------------------",
            f"Margin: {_safe_html(margin_text)}",
            f"Leverage: {_safe_html(leverage_text)}",
            f"Richtung: {_safe_html(direction_text)}",
            f"Auto-Trade: {'🟢 On' if auto_enabled else '🔴 Off'}",
        ]
    )

    markup = _build_signal_buttons(symbol)
    await bot.send_message(
        chat_id=SETTINGS.telegram_chat_id,
        text=text,
        reply_markup=markup,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
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
                f"Asset: <code>{_safe_html(symbol)}</code>\n"
                f"Aktion: <code>{_safe_html(action)}</code>"
            ),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
        return

    await _send_signal_message(symbol, action, auto_enabled)

    already_executed = bool(payload.get("executed"))

    if auto_enabled and not already_executed:
        try:
            target_chat_id = int(SETTINGS.telegram_chat_id)
        except (TypeError, ValueError):
            LOGGER.exception("Invalid TELEGRAM_CHAT_ID configured")
            return

        try:
            await execute_trade(symbol=symbol, action=action, chat_id=target_chat_id)
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

    chat = update.effective_chat
    if chat is None:
        await query.edit_message_text("⚠️ Kein Chat-Kontext für Trade vorhanden.")
        return

    try:
        success = await execute_trade(symbol=symbol, action=action, chat_id=chat.id)
    except Exception as exc:  # pragma: no cover - requires BingX failure scenarios
        LOGGER.exception("Manual trade failed: symbol=%s action=%s", symbol, action)
        await query.edit_message_text(f"⚠️ Trade fehlgeschlagen: {exc}")
        return

    if success:
        await query.edit_message_text(f"✅ Manueller Trade ausgeführt: {symbol} {action}")
    else:
        await query.edit_message_text(f"⚠️ Aktion nicht ausgeführt: {symbol} {action}")


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log unhandled errors and notify the user."""

    LOGGER.exception("Unhandled Telegram error", exc_info=context.error)

    message = None
    if hasattr(update, "effective_message"):
        message = getattr(update, "effective_message")
    if message is None and hasattr(update, "message"):
        message = getattr(update, "message")

    if message is None:
        return

    try:
        await _reply_html(
            message,
            "⚠️ Ein Fehler ist aufgetreten. Details wurden geloggt.",
        )
    except Exception:  # pragma: no cover - defensive logging
        LOGGER.debug("Failed to send error notification to user", exc_info=True)


def build_application(settings: Settings) -> Application:
    """Create the Telegram application and register handlers."""
    application = ApplicationBuilder().token(settings.telegram_bot_token).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_cmd))
    application.add_handler(CommandHandler("margin", cmd_margin))
    application.add_handler(CommandHandler("leverage", cmd_leverage))
    application.add_handler(CommandHandler("set", cmd_set))
    application.add_handler(CommandHandler("auto", auto_cmd))
    application.add_handler(
        MessageHandler(filters.COMMAND & filters.Regex(r"^/auto_"), auto_cmd)
    )
    application.add_handler(CommandHandler("manual", set_manual))
    application.add_handler(CommandHandler("botstart", bot_start))
    application.add_handler(CommandHandler("botstop", bot_stop))
    application.add_handler(CommandHandler("status", status_cmd))
    application.add_handler(CallbackQueryHandler(on_button_click))
    application.add_error_handler(on_error)
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
    if BOT is not None:
        await _ensure_command_menu(BOT)
        chat_id = _parse_chat_id(settings.telegram_chat_id)
        if chat_id is not None:
            try:
                await BOT.send_message(
                    chat_id=chat_id,
                    text=_startup_greeting_text(chat_id),
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True,
                )
            except Exception:  # pragma: no cover - network related
                LOGGER.exception("Begrüßungsnachricht konnte nicht gesendet werden")
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
