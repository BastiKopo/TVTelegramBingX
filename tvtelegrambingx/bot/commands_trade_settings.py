"""Telegram command handlers for global trade settings."""
from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from tvtelegrambingx.bot.user_prefs import get_global, set_global


async def cmd_margin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    chat = update.effective_chat
    if chat is None or message is None:
        return

    args = context.args or []
    if not args:
        prefs = get_global(chat.id)
        value = prefs.get("margin_usdt", "—")
        await message.reply_text(f"Globale Margin: {value} USDT")
        return

    try:
        margin = float(args[0])
        if margin <= 0:
            raise ValueError
    except (ValueError, TypeError):
        await message.reply_text("Nutzung: /margin <USDT>  (z. B. /margin 2)")
        return

    prefs = set_global(chat.id, margin_usdt=margin)
    await message.reply_text(f"OK. Globale Margin = {prefs['margin_usdt']:.2f} USDT")


async def cmd_leverage(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    chat = update.effective_chat
    if chat is None or message is None:
        return

    args = context.args or []
    if not args:
        prefs = get_global(chat.id)
        value = prefs.get("leverage", "—")
        await message.reply_text(f"Globaler Leverage: {value}x")
        return

    try:
        leverage = int(args[0])
        if not 1 <= leverage <= 125:
            raise ValueError
    except (ValueError, TypeError):
        await message.reply_text("Nutzung: /leverage <x>  (z. B. /leverage 25)")
        return

    prefs = set_global(chat.id, leverage=leverage)
    await message.reply_text(f"OK. Globaler Leverage = {prefs['leverage']}x")


async def cmd_set(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    chat = update.effective_chat
    if chat is None or message is None:
        return

    prefs = get_global(chat.id)
    margin = prefs.get("margin_usdt", "—")
    leverage = prefs.get("leverage", "—")
    text = (
        "Global:\n"
        f"• Margin: {margin} USDT\n"
        f"• Leverage: {leverage}x"
    )
    await message.reply_text(text)
