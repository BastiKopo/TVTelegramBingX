"""Telegram command handlers for global trade settings."""
from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from tvtelegrambingx.bot.user_prefs import get_global, set_global


def _format_percent(raw_value: object) -> str:
    if raw_value in {None, ""}:
        return "—"
    try:
        return f"{float(raw_value):.2f}%"
    except (TypeError, ValueError):
        return str(raw_value)


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
    tp_move = _format_percent(prefs.get("tp_move_percent"))
    tp_sell = _format_percent(prefs.get("tp_sell_percent"))
    text = (
        "Global:\n"
        f"• Margin: {margin} USDT\n"
        f"• Leverage: {leverage}x\n"
        f"• TP-Trigger: {tp_move}\n"
        f"• TP-Verkauf: {tp_sell}"
    )
    await message.reply_text(text)


async def cmd_tp_move(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    chat = update.effective_chat
    if chat is None or message is None:
        return

    args = context.args or []
    if not args:
        prefs = get_global(chat.id)
        value = _format_percent(prefs.get("tp_move_percent"))
        await message.reply_text(
            "Preisbewegung für dynamischen TP: "
            f"{value if value != '—' else '— (deaktiviert)'}"
        )
        return

    try:
        move_percent = float(args[0])
        if move_percent <= 0:
            raise ValueError
    except (ValueError, TypeError):
        await message.reply_text(
            "Nutzung: /tp_move <Prozent>  (z. B. /tp_move 5.5)"
        )
        return

    prefs = set_global(chat.id, tp_move_percent=move_percent)
    await message.reply_text(
        "OK. Dynamischer TP löst ab einer Bewegung von "
        f"{float(prefs['tp_move_percent']):.2f}% aus."
    )


async def cmd_tp_sell(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    chat = update.effective_chat
    if chat is None or message is None:
        return

    args = context.args or []
    if not args:
        prefs = get_global(chat.id)
        value = _format_percent(prefs.get("tp_sell_percent"))
        await message.reply_text(
            "Verkaufsanteil beim dynamischen TP: "
            f"{value if value != '—' else '— (deaktiviert)'}"
        )
        return

    try:
        sell_percent = float(args[0])
        if sell_percent <= 0 or sell_percent > 100:
            raise ValueError
    except (ValueError, TypeError):
        await message.reply_text(
            "Nutzung: /tp_sell <Prozent>  (z. B. /tp_sell 40)"
        )
        return

    prefs = set_global(chat.id, tp_sell_percent=sell_percent)
    await message.reply_text(
        "OK. Beim dynamischen TP werden "
        f"{float(prefs['tp_sell_percent']):.2f}% der Position geschlossen."
    )
