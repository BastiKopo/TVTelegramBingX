"""Minimal aiogram stub for tests."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


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


__all__ = ["F", "Router", "BaseMiddleware"]
