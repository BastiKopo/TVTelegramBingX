"""Lightweight Telegram bot integration for TradingView/BingX signals."""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Final

from .trade_executor import execute_trade

LOGGER: Final = logging.getLogger(__name__)

_TELEGRAM_BOT_TOKEN_ENV: Final = "TELEGRAM_BOT_TOKEN"
_TELEGRAM_CHAT_ID_ENV: Final = "TELEGRAM_CHAT_ID"

try:  # pragma: no cover - optional dependency setup for environments without telegram
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
except ModuleNotFoundError:  # pragma: no cover - fallback used in tests without telegram

    class InlineKeyboardButton:  # type: ignore[override]
        """Fallback InlineKeyboardButton storing text and callback data."""

        def __init__(self, text: str, callback_data: str | None = None) -> None:
            self.text = text
            self.callback_data = callback_data

    class InlineKeyboardMarkup:  # type: ignore[override]
        """Fallback InlineKeyboardMarkup storing nested button lists."""

        def __init__(self, inline_keyboard: list[list[InlineKeyboardButton]]) -> None:
            self.inline_keyboard = inline_keyboard

    class Update:  # type: ignore[override]
        """Fallback Update object providing minimal attributes for tests."""

        def __init__(self) -> None:
            self.message = None
            self.callback_query = None

try:  # pragma: no cover - optional dependency setup for environments without telegram
    from telegram.ext import (
        ApplicationBuilder,
        CallbackQueryHandler,
        CommandHandler,
        ContextTypes,
    )
except ModuleNotFoundError:  # pragma: no cover - fallback used in tests without telegram
    ApplicationBuilder = None  # type: ignore[assignment]
    CallbackQueryHandler = None  # type: ignore[assignment]
    CommandHandler = None  # type: ignore[assignment]
    ContextTypes = SimpleNamespace(DEFAULT_TYPE=object)  # type: ignore[assignment]

_AUTO_TRADE_ENABLED = False
_AUTO_TRADE_LOCK = asyncio.Lock()
_BOT_SINGLETON: "BotHandle | None" = None


@dataclass(slots=True)
class BotHandle:
    """Cache wrapper around :class:`telegram.Bot` for reuse."""

    token: str
    bot: "telegram.Bot"


async def _get_bot() -> "telegram.Bot":
    """Return a shared :class:`telegram.Bot` instance."""

    global _BOT_SINGLETON

    try:
        from telegram import Bot  # import lazily to avoid heavy dependency in tests
    except ModuleNotFoundError as exc:  # pragma: no cover - optional dependency guard
        raise RuntimeError(
            "python-telegram-bot is required to send Telegram messages"
        ) from exc

    if _BOT_SINGLETON is None:
        token = os.getenv(_TELEGRAM_BOT_TOKEN_ENV)
        if not token:
            raise RuntimeError(
                "Missing Telegram bot token. Set the TELEGRAM_BOT_TOKEN environment variable."
            )
        _BOT_SINGLETON = BotHandle(token=token, bot=Bot(token=token))

    return _BOT_SINGLETON.bot


def _get_chat_id() -> int:
    """Return the configured chat identifier."""

    chat_id_raw = os.getenv(_TELEGRAM_CHAT_ID_ENV)
    if not chat_id_raw:
        raise RuntimeError(
            "Missing Telegram chat id. Set the TELEGRAM_CHAT_ID environment variable."
        )
    try:
        return int(chat_id_raw)
    except ValueError as exc:  # pragma: no cover - configuration guard
        raise RuntimeError(
            "TELEGRAM_CHAT_ID must be an integer"
        ) from exc


async def _set_auto_trade(enabled: bool) -> None:
    """Persist the auto-trade toggle in a concurrency-safe manner."""

    global _AUTO_TRADE_ENABLED
    async with _AUTO_TRADE_LOCK:
        _AUTO_TRADE_ENABLED = enabled


async def _is_auto_trade_enabled() -> bool:
    """Return whether the auto-trade toggle is enabled."""

    async with _AUTO_TRADE_LOCK:
        return _AUTO_TRADE_ENABLED


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Telegram ``/start`` command handler."""

    del context  # unused
    if getattr(update, "message", None) is None:  # pragma: no cover - defensive guard
        return
    await update.message.reply_text(
        "🤖 TVTelegramBingX Bot gestartet.\nNutze /auto oder /manual, um den Modus zu ändern."
    )


async def set_auto(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Enable the auto-trade mode."""

    del context  # unused
    await _set_auto_trade(True)
    if getattr(update, "message", None) is None:  # pragma: no cover - defensive guard
        return
    await update.message.reply_text("✅ Auto-Trade aktiviert.")


async def set_manual(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Disable the auto-trade mode."""

    del context  # unused
    await _set_auto_trade(False)
    if getattr(update, "message", None) is None:  # pragma: no cover - defensive guard
        return
    await update.message.reply_text("❎ Manueller Modus aktiviert.")


async def handle_signal(payload: dict[str, str]) -> None:
    """Process a TradingView webhook payload by notifying Telegram."""

    symbol = payload.get("symbol")
    action = payload.get("action")
    if not symbol or not action:
        raise ValueError("Payload must include 'symbol' and 'action'")

    bot = await _get_bot()
    chat_id = _get_chat_id()

    auto_enabled = await _is_auto_trade_enabled()
    message = (
        "📊 SIGNAL\n"
        f"Asset: {symbol}\n"
        f"Aktion: {action}\n"
        f"Auto-Trade: {'On' if auto_enabled else 'Off'}"
    )

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

    await bot.send_message(chat_id=chat_id, text=message, reply_markup=markup)

    if auto_enabled:
        try:
            await execute_trade(symbol, action)
        except Exception:  # pragma: no cover - error surface handled via logs
            LOGGER.exception("Auto-trade execution failed for %s %s", symbol, action)


async def on_button_click(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle button presses originating from Telegram inline keyboards."""

    del context  # unused
    query = getattr(update, "callback_query", None)
    if query is None:  # pragma: no cover - defensive guard
        return

    await query.answer()
    data = getattr(query, "data", "") or ""
    parts = data.split("_", 2)
    if len(parts) != 3:
        await query.edit_message_text("⚠️ Ungültige Aktion erhalten.")
        LOGGER.warning("Malformed callback data received: %s", data)
        return

    action_code = f"{parts[0]}_{parts[1]}"
    symbol = parts[2]

    try:
        await execute_trade(symbol, action_code)
    except Exception:  # pragma: no cover - propagate via message/logging
        LOGGER.exception("Manual trade execution failed for %s %s", symbol, action_code)
        await query.edit_message_text("❌ Trade fehlgeschlagen. Bitte prüfe die Logs.")
    else:
        await query.edit_message_text(
            f"✅ Manueller Trade ausgeführt: {symbol} {action_code}"
        )


def run_bot() -> None:
    """Start the Telegram bot in polling mode."""

    if ApplicationBuilder is None or CallbackQueryHandler is None or CommandHandler is None:
        raise RuntimeError(
            "python-telegram-bot is required to run the Telegram bot. Install python-telegram-bot>=20."
        )

    token = os.getenv(_TELEGRAM_BOT_TOKEN_ENV)
    if not token:
        raise RuntimeError(
            "Missing Telegram bot token. Set the TELEGRAM_BOT_TOKEN environment variable."
        )

    application = ApplicationBuilder().token(token).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("auto", set_auto))
    application.add_handler(CommandHandler("manual", set_manual))
    application.add_handler(CallbackQueryHandler(on_button_click))

    LOGGER.info("Starting Telegram bot polling")
    application.run_polling()


__all__ = [
    "handle_signal",
    "on_button_click",
    "run_bot",
    "set_auto",
    "set_manual",
    "start",
]
