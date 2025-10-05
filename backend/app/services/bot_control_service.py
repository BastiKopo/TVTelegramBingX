"""Service layer for Telegram bot interactions with backend state."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from ..config import Settings
from ..repositories.bot_session_repository import BotSessionRepository
from ..repositories.signal_repository import SignalRepository
from ..repositories.user_repository import UserRepository
from ..schemas import BotState, BotSettingsUpdate, Signal


class BotControlService:
    """Expose bot-facing operations for status management and reporting."""

    def __init__(
        self,
        signal_repository: SignalRepository,
        user_repository: UserRepository,
        bot_session_repository: BotSessionRepository,
        settings: Settings,
    ) -> None:
        self._signals = signal_repository
        self._users = user_repository
        self._bot_sessions = bot_session_repository
        self._settings = settings

    async def get_state(self) -> BotState:
        session = await self._ensure_session()
        return self._context_to_state(session.context)

    async def update_state(self, update: BotSettingsUpdate) -> BotState:
        session = await self._ensure_session()
        current = self._context_to_state(session.context)
        data = current.model_dump()
        data.update(update.model_dump(exclude_unset=True))
        data["updated_at"] = datetime.now(timezone.utc)
        persisted = await self._bot_sessions.save_context(
            session,
            self._state_to_context(data.items()),
        )
        return self._context_to_state(persisted.context)

    async def recent_signals(self, limit: int = 5) -> Iterable[Signal]:
        """Return the most recent signals for reporting."""

        return await self._signals.list_recent(limit)

    async def _ensure_session(self):
        user = await self._users.get_or_create_by_username(self._settings.trading_default_username)
        return await self._bot_sessions.get_or_create_active_session(
            user.id, self._settings.trading_default_session
        )

    def _context_to_state(self, context: dict | None) -> BotState:
        data = context or {}
        updated_at = data.get("updated_at")
        if isinstance(updated_at, str):
            try:
                updated_at = datetime.fromisoformat(updated_at)
            except ValueError:
                updated_at = None
        elif not isinstance(updated_at, datetime):
            updated_at = None

        return BotState(
            auto_trade_enabled=bool(data.get("auto_trade_enabled", False)),
            manual_confirmation_required=bool(data.get("manual_confirmation_required", True)),
            margin_mode=str(data.get("margin_mode", self._settings.default_margin_mode)),
            leverage=int(data.get("leverage", self._settings.default_leverage)),
            updated_at=updated_at,
        )

    def _state_to_context(self, items: Iterable[tuple[str, object]]) -> dict:
        context: dict[str, object] = {}
        for key, value in items:
            if key == "updated_at" and isinstance(value, datetime):
                context[key] = value.astimezone(timezone.utc).replace(microsecond=0).isoformat()
            else:
                context[key] = value
        return context


__all__ = ["BotControlService"]
