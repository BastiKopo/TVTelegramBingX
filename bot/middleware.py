"""Custom middleware for authorization and dependency wiring."""
from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message

logger = logging.getLogger(__name__)


class AdminMiddleware(BaseMiddleware):
    """Restrict bot usage to whitelisted Telegram user IDs."""

    def __init__(self, admin_ids: set[int]) -> None:
        super().__init__()
        self._admin_ids = admin_ids

    async def __call__(
        self,
        handler: Callable[[Message, Dict[str, Any]], Awaitable[Any]],
        event: Message | CallbackQuery,
        data: Dict[str, Any],
    ) -> Any:
        from_user = getattr(event, "from_user", None)
        user_id = getattr(from_user, "id", None)
        if user_id is None or user_id not in self._admin_ids:
            username = getattr(from_user, "username", "unknown")
            logger.warning("Blocked unauthorized bot access", extra={"user_id": user_id, "username": username})
            if isinstance(event, Message):
                await event.answer("You are not authorized to use this bot.")
            elif isinstance(event, CallbackQuery):
                await event.answer("Unauthorized", show_alert=True)
            return None
        return await handler(event, data)


__all__ = ["AdminMiddleware"]
