"""Minimal types stub."""
from __future__ import annotations


class Message:  # pragma: no cover - placeholder
    pass


class CallbackQuery:  # pragma: no cover - placeholder
    pass


class InlineKeyboardButton:  # pragma: no cover - placeholder
    def __init__(self, text: str, callback_data: str | None = None) -> None:
        self.text = text
        self.callback_data = callback_data


class InlineKeyboardMarkup:  # pragma: no cover - placeholder
    def __init__(self, inline_keyboard: list[list[InlineKeyboardButton]]):
        self.inline_keyboard = inline_keyboard


__all__ = ["Message", "CallbackQuery", "InlineKeyboardButton", "InlineKeyboardMarkup"]
