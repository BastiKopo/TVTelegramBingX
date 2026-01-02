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

def _format_r_multiple(raw_value: object) -> str:
    if raw_value in {None, ""}:
        return "—"
    try:
        return f"{float(raw_value):.2f}R"
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


async def cmd_sl(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    chat = update.effective_chat
    if chat is None or message is None:
        return

    args = context.args or []
    if not args:
        prefs = get_global(chat.id)
        value = _format_percent(prefs.get("sl_move_percent"))
        await message.reply_text(
            "Preisbewegung für Stop-Loss: "
            f"{value if value != '—' else '— (deaktiviert)'}"
        )
        return

    try:
        sl_percent = float(args[0])
        if sl_percent <= 0:
            raise ValueError
    except (ValueError, TypeError):
        await message.reply_text("Nutzung: /sl <Prozent>  (z. B. /sl 2.5)")
        return

    prefs = set_global(chat.id, sl_move_percent=sl_percent)
    await message.reply_text(
        "OK. Stop-Loss löst bei einer Bewegung von "
        f"{float(prefs['sl_move_percent']):.2f}% gegen die Position aus."
    )


async def cmd_set(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    chat = update.effective_chat
    if chat is None or message is None:
        return

    prefs = get_global(chat.id)
    margin = prefs.get("margin_usdt", "—")
    leverage = prefs.get("leverage", "—")
    sl_move = _format_percent(prefs.get("sl_move_percent"))
    tp_move = _format_r_multiple(prefs.get("tp_move_percent"))
    tp_sell = _format_percent(prefs.get("tp_sell_percent"))
    tp2_move = _format_r_multiple(prefs.get("tp2_move_percent"))
    tp2_sell = _format_percent(prefs.get("tp2_sell_percent"))
    tp3_move = _format_r_multiple(prefs.get("tp3_move_percent"))
    tp3_sell = _format_percent(prefs.get("tp3_sell_percent"))
    text = (
        "Global:\n"
        f"• Margin: {margin} USDT\n"
        f"• Leverage: {leverage}x\n"
        f"• Stop-Loss: {sl_move}\n"
        f"• TP-Trigger: {tp_move}\n"
        f"• TP-Verkauf: {tp_sell}\n"
        f"• TP2-Trigger: {tp2_move}\n"
        f"• TP2-Verkauf: {tp2_sell}\n"
        f"• TP3-Trigger: {tp3_move}\n"
        f"• TP3-Verkauf: {tp3_sell}"
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
        value = _format_r_multiple(prefs.get("tp_move_percent"))
        await message.reply_text(
            "Preisbewegung für dynamischen TP (R-Multiple): "
            f"{value if value != '—' else '— (deaktiviert)'}"
        )
        return

    try:
        move_r = float(args[0])
        if move_r <= 0:
            raise ValueError
    except (ValueError, TypeError):
        await message.reply_text(
            "Nutzung: /tp_move <R>  (z. B. /tp_move 1.5)"
        )
        return

    prefs = set_global(chat.id, tp_move_percent=move_r)
    await message.reply_text(
        "OK. Dynamischer TP löst ab einer Bewegung von "
        f"{float(prefs['tp_move_percent']):.2f}R aus."
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


async def cmd_tp2_move(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    chat = update.effective_chat
    if chat is None or message is None:
        return

    args = context.args or []
    if not args:
        prefs = get_global(chat.id)
        value = _format_r_multiple(prefs.get("tp2_move_percent"))
        await message.reply_text(
            "Preisbewegung für dynamischen TP2 (R-Multiple): "
            f"{value if value != '—' else '— (deaktiviert)'}"
        )
        return

    try:
        move_r = float(args[0])
        if move_r <= 0:
            raise ValueError
    except (ValueError, TypeError):
        await message.reply_text(
            "Nutzung: /tp2_move <R>  (z. B. /tp2_move 2.0)"
        )
        return

    prefs = set_global(chat.id, tp2_move_percent=move_r)
    await message.reply_text(
        "OK. Zweiter dynamischer TP löst ab einer Bewegung von "
        f"{float(prefs['tp2_move_percent']):.2f}R aus."
    )


async def cmd_tp2_sell(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    chat = update.effective_chat
    if chat is None or message is None:
        return

    args = context.args or []
    if not args:
        prefs = get_global(chat.id)
        value = _format_percent(prefs.get("tp2_sell_percent"))
        await message.reply_text(
            "Verkaufsanteil beim zweiten dynamischen TP: "
            f"{value if value != '—' else '— (deaktiviert)'}"
        )
        return

    try:
        sell_percent = float(args[0])
        if sell_percent <= 0 or sell_percent > 100:
            raise ValueError
    except (ValueError, TypeError):
        await message.reply_text(
            "Nutzung: /tp2_sell <Prozent>  (z. B. /tp2_sell 60)"
        )
        return

    prefs = set_global(chat.id, tp2_sell_percent=sell_percent)
    await message.reply_text(
        "OK. Beim zweiten dynamischen TP werden "
        f"{float(prefs['tp2_sell_percent']):.2f}% der Position geschlossen."
    )


async def cmd_tp3_move(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    chat = update.effective_chat
    if chat is None or message is None:
        return

    args = context.args or []
    if not args:
        prefs = get_global(chat.id)
        value = _format_r_multiple(prefs.get("tp3_move_percent"))
        await message.reply_text(
            "Preisbewegung für dynamischen TP3 (R-Multiple): "
            f"{value if value != '—' else '— (deaktiviert)'}"
        )
        return

    try:
        move_r = float(args[0])
        if move_r <= 0:
            raise ValueError
    except (ValueError, TypeError):
        await message.reply_text(
            "Nutzung: /tp3_move <R>  (z. B. /tp3_move 3.0)"
        )
        return

    prefs = set_global(chat.id, tp3_move_percent=move_r)
    await message.reply_text(
        "OK. Dritter dynamischer TP löst ab einer Bewegung von "
        f"{float(prefs['tp3_move_percent']):.2f}R aus."
    )


async def cmd_tp3_sell(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    chat = update.effective_chat
    if chat is None or message is None:
        return

    args = context.args or []
    if not args:
        prefs = get_global(chat.id)
        value = _format_percent(prefs.get("tp3_sell_percent"))
        await message.reply_text(
            "Verkaufsanteil beim dritten dynamischen TP: "
            f"{value if value != '—' else '— (deaktiviert)'}"
        )
        return

    try:
        sell_percent = float(args[0])
        if sell_percent <= 0 or sell_percent > 100:
            raise ValueError
    except (ValueError, TypeError):
        await message.reply_text(
            "Nutzung: /tp3_sell <Prozent>  (z. B. /tp3_sell 70)"
        )
        return

    prefs = set_global(chat.id, tp3_sell_percent=sell_percent)
    await message.reply_text(
        "OK. Beim dritten dynamischen TP werden "
        f"{float(prefs['tp3_sell_percent']):.2f}% der Position geschlossen."
    )
