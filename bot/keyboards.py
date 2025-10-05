"""Inline keyboard builders for Telegram bot interactions."""
from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from .models import BotState


def main_menu(state: BotState) -> InlineKeyboardMarkup:
    """Return the main inline keyboard for the status view."""

    auto_text = "Auto-Trade: ON" if state.auto_trade_enabled else "Auto-Trade: OFF"
    confirm_text = (
        "Manual Confirmations: ON" if state.manual_confirmation_required else "Manual Confirmations: OFF"
    )
    margin_text = f"Margin: {state.margin_mode.title()}"
    leverage_text = f"Leverage: x{state.leverage}"

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=auto_text, callback_data="toggle:auto_trade")],
            [InlineKeyboardButton(text=confirm_text, callback_data="toggle:manual")],
            [
                InlineKeyboardButton(text="Isolated", callback_data="margin:isolated"),
                InlineKeyboardButton(text="Cross", callback_data="margin:cross"),
            ],
            [
                InlineKeyboardButton(text="x3", callback_data="leverage:3"),
                InlineKeyboardButton(text="x5", callback_data="leverage:5"),
                InlineKeyboardButton(text="x10", callback_data="leverage:10"),
                InlineKeyboardButton(text="x20", callback_data="leverage:20"),
            ],
            [InlineKeyboardButton(text=margin_text, callback_data="noop:margin")],
            [InlineKeyboardButton(text=leverage_text, callback_data="noop:leverage")],
            [InlineKeyboardButton(text="Refresh", callback_data="refresh:status")],
        ]
    )


__all__ = ["main_menu"]
