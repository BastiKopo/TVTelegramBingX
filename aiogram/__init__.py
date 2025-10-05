"""Minimal aiogram stub for tests."""
from __future__ import annotations

from typing import Any, Callable


class _DummySession:
    async def close(self) -> None:  # pragma: no cover - noop for tests
        return None


class Bot:
    """Minimal Bot stub implementing only the bits used in tests."""

    def __init__(self, token: str, parse_mode: str | None = None) -> None:
        self.token = token
        self.parse_mode = parse_mode
        self.session = _DummySession()

    async def send_message(self, chat_id: int, text: str) -> None:  # pragma: no cover - noop
        return None


class _MiddlewareRegistry:
    def middleware(self, *args: Any, **kwargs: Any) -> None:  # pragma: no cover - noop
        return None


class Dispatcher:
    """Minimal dispatcher stub used by tests."""

    def __init__(self) -> None:
        self.message = _MiddlewareRegistry()
        self.callback_query = _MiddlewareRegistry()

    def include_router(self, router: Any) -> None:  # pragma: no cover - noop
        return None

    def resolve_used_update_types(self) -> list[str]:  # pragma: no cover - noop
        return []

    async def start_polling(self, *args: Any, **kwargs: Any) -> None:  # pragma: no cover - noop
        return None


class F:  # pragma: no cover - placeholder
    pass


class _HandlerRegistry:
    def register(self, *args: Any, **kwargs: Any) -> None:  # pragma: no cover - noop
        return None


class Router:
    def __init__(self, name: str | None = None) -> None:
        self.name = name
        self.message = _HandlerRegistry()
        self.callback_query = _HandlerRegistry()


class BaseMiddleware:
    def __init__(self) -> None:
        pass


__all__ = ["F", "Router", "BaseMiddleware", "Bot", "Dispatcher"]
