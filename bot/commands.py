"""Telegram command handlers for margin/leverage preferences."""

from __future__ import annotations

from typing import Any

from bot.user_prefs import get_global, get_symbol, set_global, set_symbol
from utils.symbols import is_symbol, norm_symbol

try:  # pragma: no cover - optional dependency for type checking
    from telegram import Update
    from telegram.ext import ContextTypes
except ModuleNotFoundError:  # pragma: no cover - fallback during tests without telegram
    Update = Any  # type: ignore
    ContextTypes = Any  # type: ignore


async def cmd_margin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:  # type: ignore[attr-defined]
    args = context.args or []
    chat = update.effective_chat.id  # type: ignore[assignment]

    if not args:
        prefs = get_global(chat)
        margin = prefs.get("margin_usdt", "—")
        await update.message.reply_text(f"Globale Margin: {margin} USDT")  # type: ignore[union-attr]
        return

    if len(args) == 1:
        try:
            margin_value = float(args[0])
            assert margin_value > 0
        except Exception:
            await update.message.reply_text("Nutzung: /margin [<symbol>] <USDT>")  # type: ignore[union-attr]
            return

        prefs = set_global(chat, margin_usdt=margin_value)
        await update.message.reply_text(  # type: ignore[union-attr]
            f"OK. Globale Margin = {prefs['margin_usdt']:.2f} USDT"
        )
        return

    symbol = norm_symbol(args[0])
    if not is_symbol(symbol):
        await update.message.reply_text("Ungültiges Symbol (z. B. LTC-USDT)")  # type: ignore[union-attr]
        return

    try:
        margin_value = float(args[1])
        assert margin_value > 0
    except Exception:
        await update.message.reply_text("Ungültige Margin.")  # type: ignore[union-attr]
        return

    prefs = set_symbol(chat, symbol, margin_usdt=margin_value)
    await update.message.reply_text(  # type: ignore[union-attr]
        f"OK. {symbol}: Margin = {prefs['margin_usdt']:.2f} USDT"
    )


async def cmd_leverage(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:  # type: ignore[attr-defined]
    args = context.args or []
    chat = update.effective_chat.id  # type: ignore[assignment]

    if not args:
        prefs = get_global(chat)
        leverage = prefs.get("leverage", "—")
        await update.message.reply_text(f"Globaler Leverage: {leverage}x")  # type: ignore[union-attr]
        return

    if len(args) == 1:
        try:
            leverage_value = int(args[0])
            assert 1 <= leverage_value <= 125
        except Exception:
            await update.message.reply_text("Nutzung: /leverage [<symbol>] <x>")  # type: ignore[union-attr]
            return

        prefs = set_global(chat, leverage=leverage_value)
        await update.message.reply_text(  # type: ignore[union-attr]
            f"OK. Globaler Leverage = {prefs['leverage']}x"
        )
        return

    symbol = norm_symbol(args[0])
    if not is_symbol(symbol):
        await update.message.reply_text("Ungültiges Symbol.")  # type: ignore[union-attr]
        return

    try:
        leverage_value = int(args[1])
        assert 1 <= leverage_value <= 125
    except Exception:
        await update.message.reply_text("Ungültiger Leverage (1–125).")  # type: ignore[union-attr]
        return

    prefs = set_symbol(chat, symbol, leverage=leverage_value)
    await update.message.reply_text(  # type: ignore[union-attr]
        f"OK. {symbol}: Leverage = {prefs['leverage']}x"
    )


async def cmd_set(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:  # type: ignore[attr-defined]
    chat = update.effective_chat.id  # type: ignore[assignment]
    args = context.args or []

    if args:
        symbol = norm_symbol(args[0])
        prefs = get_symbol(chat, symbol)
        await update.message.reply_text(  # type: ignore[union-attr]
            f"{symbol}\n"
            f"• Margin: {prefs.get('margin_usdt', '—')} USDT\n"
            f"• Leverage: {prefs.get('leverage', '—')}x"
        )
        return

    prefs = get_global(chat)
    await update.message.reply_text(  # type: ignore[union-attr]
        "Global\n"
        f"• Margin: {prefs.get('margin_usdt', '—')} USDT\n"
        f"• Leverage: {prefs.get('leverage', '—')}x"
    )
