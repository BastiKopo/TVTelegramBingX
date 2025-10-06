"""Minimal FastAPI compatibility layer for tests."""

from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, Optional


class HTTPException(Exception):
    """Simplified HTTP exception matching the FastAPI interface used in tests."""

    def __init__(self, *, status_code: int, detail: Any = None) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class Request:
    """Very small subset of :class:`fastapi.Request` used by the project."""

    def __init__(self, json_data: Any | None = None, headers: Optional[Dict[str, str]] = None) -> None:
        self._json = json_data
        self.headers = headers or {}

    async def json(self) -> Any:
        return self._json


@dataclass
class _Route:
    method: str
    path: str
    handler: Callable[..., Any]
    response_class: Any | None = None


class FastAPI:
    """Tiny re-implementation of :class:`fastapi.FastAPI` for local tests."""

    def __init__(self, title: str = "FastAPI", version: str = "0.1.0") -> None:
        self.title = title
        self.version = version
        self.docs_url: str | None = "/docs"
        self._routes: list[_Route] = []

    def _register_route(
        self, method: str, path: str, handler: Callable[..., Any], response_class: Any | None = None
    ) -> Callable[..., Any]:
        self._routes.append(_Route(method=method, path=path, handler=handler, response_class=response_class))
        return handler

    def get(self, path: str, response_class: Any | None = None) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            return self._register_route("GET", path, func, response_class)

        return decorator

    def post(self, path: str, response_class: Any | None = None) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            return self._register_route("POST", path, func, response_class)

        return decorator

    def _find_route(self, method: str, path: str) -> _Route | None:
        for route in self._routes:
            if route.method == method and route.path == path:
                return route
        return None

    async def _dispatch(self, method: str, path: str, request: Request) -> Any:
        route = self._find_route(method, path)
        if route is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")

        handler = route.handler
        signature = inspect.signature(handler)
        if len(signature.parameters) >= 1:
            result = handler(request)
        else:
            result = handler()

        if asyncio.iscoroutine(result):
            result = await result

        return result


class status:
    HTTP_200_OK = 200
    HTTP_201_CREATED = 201
    HTTP_400_BAD_REQUEST = 400
    HTTP_403_FORBIDDEN = 403
    HTTP_404_NOT_FOUND = 404
    HTTP_500_INTERNAL_SERVER_ERROR = 500


__all__ = ["FastAPI", "HTTPException", "Request", "status"]
