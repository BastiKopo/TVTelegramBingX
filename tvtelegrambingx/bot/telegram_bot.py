"""Telegram bot handling auto-trade toggles and manual execution."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, Optional, Sequence

import html

from telegram import (
    Bot,
    BotCommand,
    BotCommandScopeAllChatAdministrators,
    BotCommandScopeAllGroupChats,
    BotCommandScopeAllPrivateChats,
    BotCommandScopeChat,
    BotCommandScopeDefault,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
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
    cmd_sl,
    cmd_set,
    cmd_tp_atr,
    cmd_tp_move,
    cmd_tp2_atr,
    cmd_tp2_move,
    cmd_tp2_sell,
    cmd_tp3_atr,
    cmd_tp3_move,
    cmd_tp3_sell,
    cmd_tp4_atr,
    cmd_tp4_move,
    cmd_tp4_sell,
    cmd_tp_sell,
)
from tvtelegrambingx.bot.trade_executor import execute_trade
from tvtelegrambingx.bot.user_prefs import get_global
from tvtelegrambingx.config import Settings
from tvtelegrambingx.config_store import ConfigStore
from tvtelegrambingx.integrations.bingx_account import get_status_summary
from tvtelegrambingx.utils.schedule import is_within_schedule, parse_time_windows

LOGGER = logging.getLogger(__name__)

_COMMAND_DEFINITIONS = (
    ("start", "Begrüßung & aktueller Status", "/start"),
    ("help", "Befehlsübersicht", "/help"),
    ("status", "PnL & Trading-Setup anzeigen", "/status"),
    ("auto", "Auto-Trade global schalten", "/auto on|off"),
    ("margin", "Globale Margin anzeigen/setzen", "/margin [USDT]"),
    ("leverage", "Globalen Leverage anzeigen/setzen", "/leverage [x]"),
    ("sl", "Trailing Stop-Loss Abstand einstellen", "/sl [Prozent]"),
    ("tp_move", "Preisbewegung für dynamischen TP (R-Multiple)", "/tp_move [R]"),
    ("tp_atr", "Preisbewegung für dynamischen TP (ATR)", "/tp_atr [ATR]"),
    ("tp_sell", "Teilverkauf beim dynamischen TP", "/tp_sell [Prozent]"),
    ("tp2_move", "Preisbewegung für zweiten TP (R-Multiple)", "/tp2_move [R]"),
    ("tp2_atr", "Preisbewegung für zweiten TP (ATR)", "/tp2_atr [ATR]"),
    ("tp2_sell", "Teilverkauf beim zweiten TP", "/tp2_sell [Prozent]"),
    ("tp3_move", "Preisbewegung für dritten TP (R-Multiple)", "/tp3_move [R]"),
    ("tp3_atr", "Preisbewegung für dritten TP (ATR)", "/tp3_atr [ATR]"),
    ("tp3_sell", "Teilverkauf beim dritten TP", "/tp3_sell [Prozent]"),
    ("tp4_move", "Preisbewegung für vierten TP (R-Multiple)", "/tp4_move [R]"),
    ("tp4_atr", "Preisbewegung für vierten TP (ATR)", "/tp4_atr [ATR]"),
    ("tp4_sell", "Teilverkauf beim vierten TP", "/tp4_sell [Prozent]"),
    ("set", "Aktuelle globale Werte anzeigen", "/set"),
)

_ADDITIONAL_HELP_LINES = (
    (None, "Auto-Trade deaktivieren (Alias)", "/manual"),
    (None, "Bot starten (Signale annehmen)", "/botstart"),
    (None, "Bot stoppen (Signale ignorieren)", "/botstop"),
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
ACTIVE_WINDOWS = []


def configure(settings: Settings) -> None:
    """Initialise global settings and bot instance."""
    global SETTINGS, BOT
    SETTINGS = settings
    BOT = Bot(token=settings.telegram_bot_token)
    try:
        global ACTIVE_WINDOWS
        ACTIVE_WINDOWS = parse_time_windows(settings.trading_active_hours)
    except ValueError as exc:
        raise RuntimeError(str(exc)) from exc
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


def _format_signal_message(
    symbol: str,
    margin_text: str,
    leverage_text: str,
    direction_texts: Sequence[str],
    auto_enabled: bool,
) -> str:
    auto_text = "🟢 On" if auto_enabled else "🔴 Off"
    directions = list(direction_texts) or ["—"]

    lines = [
        f"📊 Signal - {_safe_html(_format_symbol(symbol))}",
        "---------------------------------------",
        f"Margin: {_safe_html(margin_text)}",
        f"Leverage: {_safe_html(leverage_text)}",
    ]

    if len(directions) == 1:
        lines.append(f"Richtung: {_safe_html(directions[0])}")
    else:
        lines.append("Richtung:")
        lines.extend(f"• {_safe_html(direction)}" for direction in directions)

    lines.append(f"Auto-Trade: {_safe_html(auto_text)}")

    return "\n".join(lines)


def _format_symbol(symbol: str) -> str:
    cleaned = "".join(ch for ch in str(symbol) if ch.isalnum())
    if not cleaned:
        cleaned = str(symbol)
    return cleaned.upper()


def _direction_from_action(action: str) -> str:
    action_upper = str(action or "").upper().strip()

    mapping = {
        "LONG_BUY": "Long öffnen",
        "LONG_SELL": "Long schließen",
        "SHORT_SELL": "Short öffnen",
        "SHORT_BUY": "Short schließen",
    }

    if action_upper in mapping:
        return mapping[action_upper]

    if "SHORT" in action_upper and "BUY" in action_upper:
        return "Short schließen"
    if "SHORT" in action_upper and "SELL" in action_upper:
        return "Short öffnen"
    if "LONG" in action_upper and "SELL" in action_upper:
        return "Long schließen"
    if "LONG" in action_upper and "BUY" in action_upper:
        return "Long öffnen"

    if "SHORT" in action_upper:
        return "Short"
    if "LONG" in action_upper:
        return "Long"
    if "SELL" in action_upper:
        return "Short"
    if "BUY" in action_upper:
        return "Long"

    return action_upper or "—"


def _startup_greeting_text() -> str:
    """Return the minimal startup status banner for Telegram."""

    _refresh_auto_trade_cache()
    auto_text = _safe_html("🟢" if AUTO_TRADE else "🔴")
    bot_text = _safe_html("🟢" if BOT_ENABLED else "🔴")

    return "\n".join(
        [
            "🤖 TVTelegramBingX",
            "---------------------------------------",
            f"Bot ist Aktiv {bot_text} und im Autobetrieb: {auto_text}",
        ]
    )


async def _ensure_command_menu(
    bot: Bot,
    chat_id: Optional[int] = None,
    language_code: Optional[str] = None,
) -> None:
    commands = [
        BotCommand(command=name, description=description)
        for name, description, _ in _COMMAND_DEFINITIONS
    ]
    scopes = [
        BotCommandScopeDefault(),
        BotCommandScopeAllPrivateChats(),
        BotCommandScopeAllGroupChats(),
        BotCommandScopeAllChatAdministrators(),
    ]
    language_codes = [None, "de", "de-DE", "de-AT", "de-CH", "de-LI", "de-LU"]
    if language_code:
        language_codes.append(language_code)
        normalized = language_code.replace("_", "-")
        language_codes.append(normalized)
        language_codes.append(normalized.lower())
    language_codes = list(dict.fromkeys(language_codes))
    for scope in scopes:
        for language_code in language_codes:
            try:
                await bot.delete_my_commands(scope=scope, language_code=language_code)
                await bot.set_my_commands(
                    commands, scope=scope, language_code=language_code
                )
            except Exception:  # pragma: no cover - network/telegram errors
                LOGGER.warning(
                    "Konnte Telegram-Befehle nicht aktualisieren (scope=%s, lang=%s)",
                    scope.__class__.__name__,
                    language_code,
                    exc_info=True,
                )
    if chat_id is not None:
        for language_code in language_codes:
            try:
                await bot.delete_my_commands(
                    scope=BotCommandScopeChat(chat_id),
                    language_code=language_code,
                )
                await bot.set_my_commands(
                    commands,
                    scope=BotCommandScopeChat(chat_id),
                    language_code=language_code,
                )
            except Exception:  # pragma: no cover - network/telegram errors
                LOGGER.warning(
                    "Konnte Telegram-Befehle nicht aktualisieren (scope=chat, lang=%s)",
                    language_code,
                    exc_info=True,
                )


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

    user_language = update.effective_user.language_code if update.effective_user else None
    try:
        await _ensure_command_menu(
            context.bot,
            chat_id=update.effective_chat.id,
            language_code=user_language,
        )
    except Exception:  # pragma: no cover - network related
        LOGGER.exception("Bot-Kommandos konnten nicht aktualisiert werden")

    text = _startup_greeting_text()
    await _reply_html(message, text)


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Return only the command overview."""
    message = update.effective_message
    if message is None:
        return
    user_language = update.effective_user.language_code if update.effective_user else None
    try:
        await _ensure_command_menu(
            context.bot,
            chat_id=update.effective_chat.id,
            language_code=user_language,
        )
    except Exception:  # pragma: no cover - network related
        LOGGER.exception("Bot-Kommandos konnten nicht aktualisiert werden")
    await _reply_html(message, _menu_text_html())


async def unknown_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle unknown commands with a short hint."""
    message = update.effective_message
    if message is None:
        return
    await _reply_html(
        message,
        "\n".join(
            [
                "⚠️ Unbekannter Befehl.",
                "TP4-Befehle: /tp4_move, /tp4_atr, /tp4_sell",
                "",
                _menu_text_html(),
            ]
        ),
    )


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


async def _send_signal_message(symbol: str, actions: Sequence[str], auto_enabled: bool) -> None:
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
    direction_texts = [_direction_from_action(action) for action in actions]

    text = _format_signal_message(
        symbol,
        margin_text,
        leverage_text,
        direction_texts,
        auto_enabled,
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
    raw_actions = payload.get("actions")
    if isinstance(raw_actions, (list, tuple, set)):
        actions = [str(action).upper() for action in raw_actions if str(action or "").strip()]
    else:
        action_value = payload.get("action")
        actions = [str(action_value).upper()] if action_value else []

    if not symbol or not actions:
        LOGGER.warning("Invalid payload: %s", payload)
        return

    auto_enabled = CONFIG.get_auto_trade(symbol)
    LOGGER.info(
        "Received signal: symbol=%s actions=%s auto=%s",
        symbol,
        actions,
        auto_enabled,
    )

    now = datetime.now()
    if not is_within_schedule(
        now, ACTIVE_WINDOWS, SETTINGS.trading_disable_weekends
    ):
        bot = APPLICATION.bot if APPLICATION is not None else BOT
        if bot is None:
            LOGGER.error("No Telegram bot available to send schedule notification")
            return
        actions_text = ", ".join(f"<code>{_safe_html(action)}</code>" for action in actions)
        reasons = []
        if SETTINGS.trading_disable_weekends and now.weekday() >= 5:
            reasons.append("Wochenende")
        if ACTIVE_WINDOWS:
            configured = SETTINGS.trading_active_hours or ""
            reasons.append(f"aktive Zeiten: {configured}")
        reason_text = " & ".join(reasons) or "außerhalb der aktiven Zeiten"
        await bot.send_message(
            chat_id=SETTINGS.telegram_chat_id,
            text=(
                f"⏸ Signal ignoriert ({_safe_html(reason_text)}).\n"
                f"Asset: <code>{_safe_html(symbol)}</code>\n"
                f"Aktion: {actions_text or '—'}"
            ),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
        return

    if not BOT_ENABLED:
        bot = APPLICATION.bot if APPLICATION is not None else BOT
        if bot is None:
            LOGGER.error("No Telegram bot available to send disabled notification")
            return
        actions_text = ", ".join(f"<code>{_safe_html(action)}</code>" for action in actions)
        await bot.send_message(
            chat_id=SETTINGS.telegram_chat_id,
            text=(
                "⏸ Signal empfangen, aber Bot ist gestoppt.\n"
                f"Asset: <code>{_safe_html(symbol)}</code>\n"
                f"Aktion: {actions_text or '—'}"
            ),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
        return

    await _send_signal_message(symbol, actions, auto_enabled)

    already_executed = bool(payload.get("executed"))

    if auto_enabled and not already_executed:
        try:
            target_chat_id = int(SETTINGS.telegram_chat_id)
        except (TypeError, ValueError):
            LOGGER.exception("Invalid TELEGRAM_CHAT_ID configured")
            return

        for action in actions:
            try:
                await execute_trade(symbol=symbol, action=action, chat_id=target_chat_id)
            except Exception as exc:  # pragma: no cover - requires BingX failure scenarios
                LOGGER.exception("Auto trade failed: symbol=%s action=%s", symbol, action)


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
    application.add_handler(CommandHandler("sl", cmd_sl))
    application.add_handler(CommandHandler("tp_move", cmd_tp_move))
    application.add_handler(CommandHandler("tp_atr", cmd_tp_atr))
    application.add_handler(CommandHandler("tp_sell", cmd_tp_sell))
    application.add_handler(CommandHandler("tp2_move", cmd_tp2_move))
    application.add_handler(CommandHandler("tp2_atr", cmd_tp2_atr))
    application.add_handler(CommandHandler("tp2_sell", cmd_tp2_sell))
    application.add_handler(CommandHandler("tp3_move", cmd_tp3_move))
    application.add_handler(CommandHandler("tp3_atr", cmd_tp3_atr))
    application.add_handler(CommandHandler("tp3_sell", cmd_tp3_sell))
    application.add_handler(CommandHandler("tp4_move", cmd_tp4_move))
    application.add_handler(CommandHandler("tp4_atr", cmd_tp4_atr))
    application.add_handler(CommandHandler("tp4_sell", cmd_tp4_sell))
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
    application.add_handler(MessageHandler(filters.COMMAND, unknown_cmd))
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
        await _ensure_command_menu(BOT, chat_id=chat_id)
        chat_id = _parse_chat_id(settings.telegram_chat_id)
        if chat_id is not None:
            try:
                await BOT.send_message(
                    chat_id=chat_id,
                    text=_startup_greeting_text(),
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
