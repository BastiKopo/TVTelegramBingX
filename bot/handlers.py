"""Telegram command and callback handlers."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Iterable

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from .backend_client import BackendClient
from .config import BotSettings
from .keyboards import main_menu
from .models import BotState, SignalRead

logger = logging.getLogger(__name__)


class BotHandlers:
    """Collection of Telegram bot handlers with injected dependencies."""

    def __init__(self, client: BackendClient, settings: BotSettings) -> None:
        self._client = client
        self._settings = settings

    async def start(self, message: Message) -> None:
        await self.help(message)

    async def help(self, message: Message) -> None:
        text = (
            "<b>TVTelegramBingX Control Bot</b>\n\n"
            "Available commands:\n"
            "/status - Show current automation status\n"
            "/autotrade - Toggle auto-trading\n"
            "/confirmations - Toggle manual confirmations\n"
            "/margin [isolated|cross] - Set margin mode\n"
            "/leverage [value] - Set leverage multiplier\n"
            "/reports - Show recent signals\n"
            "/help - Show this message"
        )
        await message.answer(text, disable_web_page_preview=True)

    async def status(self, message: Message) -> None:
        state = await self._client.get_state()
        await self._respond(message, state)
        self._audit(message, "status", state)

    async def toggle_autotrade(self, message: Message) -> None:
        await self._toggle_auto_trade(message)

    async def toggle_manual_confirmations(self, message: Message) -> None:
        await self._toggle_manual(message)

    async def margin(self, message: Message) -> None:
        mode = self._extract_argument(message.text)
        if mode in {"isolated", "cross"}:
            new_state = await self._client.update_state(margin_mode=mode)
            await self._respond(message, new_state, notice=f"Margin mode updated to {mode}")
            self._audit(message, "margin", new_state)
            return
        await self.status(message)

    async def leverage(self, message: Message) -> None:
        argument = self._extract_argument(message.text)
        if argument is not None:
            try:
                leverage = int(argument)
            except ValueError:
                await message.answer("Please provide a numeric leverage value, e.g. /leverage 5")
                return
            new_state = await self._client.update_state(leverage=leverage)
            await self._respond(message, new_state, notice=f"Leverage updated to x{leverage}")
            self._audit(message, "leverage", new_state)
            return
        await self.status(message)

    async def reports(self, message: Message) -> None:
        signals = await self._client.fetch_recent_signals(self._settings.report_limit)
        text = self._format_signals(signals)
        await message.answer(text, disable_web_page_preview=True)
        self._audit(message, "reports", {"count": len(signals)})

    async def refresh_callback(self, callback: CallbackQuery) -> None:
        state = await self._client.get_state()
        await self._respond(callback, state, notice="Status updated")
        self._audit(callback, "status-refresh", state)

    async def toggle_autotrade_callback(self, callback: CallbackQuery) -> None:
        await self._toggle_auto_trade(callback)

    async def toggle_manual_callback(self, callback: CallbackQuery) -> None:
        await self._toggle_manual(callback)

    async def margin_callback(self, callback: CallbackQuery) -> None:
        mode = (callback.data or "").split(":", 1)[-1]
        if mode not in {"isolated", "cross"}:
            await callback.answer("Unknown margin mode")
            return
        state = await self._client.update_state(margin_mode=mode)
        await self._respond(callback, state, notice=f"Margin set to {mode}")
        self._audit(callback, "margin", state)

    async def leverage_callback(self, callback: CallbackQuery) -> None:
        value = (callback.data or "").split(":", 1)[-1]
        try:
            leverage = int(value)
        except ValueError:
            await callback.answer("Invalid leverage value")
            return
        state = await self._client.update_state(leverage=leverage)
        await self._respond(callback, state, notice=f"Leverage set to x{leverage}")
        self._audit(callback, "leverage", state)

    async def noop_callback(self, callback: CallbackQuery) -> None:
        await callback.answer()

    def _format_signals(self, signals: Iterable[SignalRead]) -> str:
        if not signals:
            return "No recent signals were found."
        lines = ["<b>Recent Signals</b>"]
        for signal in signals:
            timestamp = signal.timestamp.strftime("%Y-%m-%d %H:%M:%S")
            lines.append(
                f"• {signal.symbol} — <b>{signal.action.upper()}</b> — qty {signal.quantity} at {timestamp}"
            )
        return "\n".join(lines)

    async def _toggle_auto_trade(self, event: Message | CallbackQuery) -> None:
        state = await self._client.get_state()
        new_state = await self._client.update_state(auto_trade_enabled=not state.auto_trade_enabled)
        notice = "Auto-Trade enabled" if new_state.auto_trade_enabled else "Auto-Trade disabled"
        await self._respond(event, new_state, notice=notice)
        self._audit(event, "autotrade", new_state)

    async def _toggle_manual(self, event: Message | CallbackQuery) -> None:
        state = await self._client.get_state()
        new_state = await self._client.update_state(
            manual_confirmation_required=not state.manual_confirmation_required
        )
        notice = (
            "Manual confirmations enabled"
            if new_state.manual_confirmation_required
            else "Manual confirmations disabled"
        )
        await self._respond(event, new_state, notice=notice)
        self._audit(event, "manual", new_state)

    async def _respond(self, event: Message | CallbackQuery, state: BotState, *, notice: str | None = None) -> None:
        text = self._format_state(state)
        markup = main_menu(state)
        if isinstance(event, CallbackQuery):
            if notice:
                await event.answer(notice)
            else:
                await event.answer()
            if event.message:
                await event.message.edit_text(text, reply_markup=markup, disable_web_page_preview=True)
        else:
            body = f"{notice}\n\n{text}" if notice else text
            await event.answer(body, reply_markup=markup, disable_web_page_preview=True)

    def _format_state(self, state: BotState) -> str:
        updated = state.updated_at
        if isinstance(updated, datetime):
            updated_text = updated.strftime("%Y-%m-%d %H:%M:%S UTC")
        else:
            updated_text = "never"
        lines = [
            "<b>Automation Status</b>",
            f"Auto-Trade: {'ON' if state.auto_trade_enabled else 'OFF'}",
            f"Manual Confirmations: {'ON' if state.manual_confirmation_required else 'OFF'}",
            f"Margin Mode: {state.margin_mode}",
            f"Leverage: x{state.leverage}",
            f"Last Updated: {updated_text}",
        ]

        lines.append("")
        lines.append("<b>Balances</b>")
        if state.balances:
            for balance in state.balances:
                lines.append(
                    f"• {balance.asset}: free {balance.free:.4f}, locked {balance.locked:.4f}, total {balance.total:.4f}"
                )
        else:
            lines.append("• None recorded")

        lines.append("")
        lines.append("<b>PnL</b>")
        lines.append(f"Realized: {state.pnl.realized:.2f}")
        lines.append(f"Unrealized: {state.pnl.unrealized:.2f}")
        lines.append(f"Total: {state.pnl.total:.2f}")

        lines.append("")
        lines.append("<b>Open Positions</b>")
        if state.open_positions:
            for position in state.open_positions:
                opened = (
                    position.opened_at.strftime("%Y-%m-%d %H:%M:%S UTC")
                    if isinstance(position.opened_at, datetime)
                    else "unknown"
                )
                leverage = f"x{position.leverage}" if position.leverage else "—"
                lines.append(
                    "• {symbol} — {side} qty {quantity:.4f} @ {price:.4f} (lev {lev}) opened {opened}".format(
                        symbol=position.symbol,
                        side=position.action.upper(),
                        quantity=position.quantity,
                        price=position.entry_price,
                        lev=leverage,
                        opened=opened,
                    )
                )
        else:
            lines.append("• No open positions")

        return "\n".join(lines)

    def _audit(self, event: Message | CallbackQuery, action: str, payload: object) -> None:
        user = getattr(event, "from_user", None)
        user_id = getattr(user, "id", None)
        username = getattr(user, "username", None)
        logger.info(
            "Bot action executed",
            extra={"action": action, "user_id": user_id, "username": username, "payload": payload},
        )

    def _extract_argument(self, text: str | None) -> str | None:
        if not text:
            return None
        parts = text.split()
        if len(parts) < 2:
            return None
        return parts[1].strip()


def build_router(handlers: BotHandlers) -> Router:
    router = Router(name="bot-handlers")
    router.message.register(handlers.start, Command(commands=["start"]))
    router.message.register(handlers.help, Command(commands=["help"]))
    router.message.register(handlers.status, Command(commands=["status"]))
    router.message.register(handlers.toggle_autotrade, Command(commands=["autotrade"]))
    router.message.register(handlers.toggle_manual_confirmations, Command(commands=["confirmations"]))
    router.message.register(handlers.margin, Command(commands=["margin"]))
    router.message.register(handlers.leverage, Command(commands=["leverage"]))
    router.message.register(handlers.reports, Command(commands=["reports"]))

    router.callback_query.register(handlers.refresh_callback, F.data == "refresh:status")
    router.callback_query.register(handlers.toggle_autotrade_callback, F.data == "toggle:auto_trade")
    router.callback_query.register(handlers.toggle_manual_callback, F.data == "toggle:manual")
    router.callback_query.register(handlers.margin_callback, F.data.startswith("margin:"))
    router.callback_query.register(handlers.leverage_callback, F.data.startswith("leverage:"))
    router.callback_query.register(handlers.noop_callback, F.data.startswith("noop:"))
    return router


__all__ = ["BotHandlers", "build_router"]
