"""Minimal FastAPI compatibility layer for tests."""

from __future__ import annotations

import asyncio
import inspect
import json
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, Optional

from .responses import HTMLResponse


class HTTPException(Exception):
    """Simplified HTTP exception matching the FastAPI interface used in tests."""

    def __init__(self, *, status_code: int, detail: Any = None) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class Request:
    """Very small subset of :class:`fastapi.Request` used by the project."""

    def __init__(
        self,
        json_data: Any | None = None,
        body: bytes | None = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> None:
        self._json = json_data
        self._body = body or b""
        self.headers = headers or {}

    async def json(self) -> Any:
        return self._json

    @property
    def body(self) -> bytes:
        return self._body


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

    async def _dispatch(self, method: str, path: str, request: Request) -> tuple[Any, _Route]:
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

        return result, route

    async def __call__(self, scope: Dict[str, Any], receive: Callable[[], Awaitable[Dict[str, Any]]], send: Callable[[Dict[str, Any]], Awaitable[None]]) -> None:
        """ASGI entrypoint so the shim can be used with uvicorn in production."""

        if scope.get("type") != "http":  # pragma: no cover - only http is required
            raise RuntimeError("Only HTTP scope is supported by the FastAPI shim")

        method = scope.get("method", "GET").upper()
        path = scope.get("path", "/")

        raw_headers = scope.get("headers") or []
        headers = {key.decode().lower(): value.decode() for key, value in raw_headers}

        body_chunks: list[bytes] = []
        more_body = True
        while more_body:
            message = await receive()
            body = message.get("body", b"")
            if body:
                body_chunks.append(body)
            more_body = message.get("more_body", False)

        body_bytes = b"".join(body_chunks)
        json_payload: Any | None = None
        if body_bytes:
            try:
                json_payload = json.loads(body_bytes.decode())
            except (UnicodeDecodeError, json.JSONDecodeError):
                json_payload = None

        request = Request(json_data=json_payload, body=body_bytes, headers=headers)

        status_code = status.HTTP_200_OK
        response_body: Any
        route: _Route | None = None
        try:
            response_body, route = await self._dispatch(method, path, request)
        except HTTPException as exc:
            status_code = exc.status_code
            response_body = exc.detail if exc.detail is not None else ""

        raw_body: bytes
        response_headers: Dict[str, str] = {}

        if isinstance(response_body, HTMLResponse):
            response_class = HTMLResponse
            response_body = response_body.content
        else:
            response_class = route.response_class if route else None

        if isinstance(response_body, (dict, list)):
            raw_body = json.dumps(response_body).encode()
            response_headers["content-type"] = "application/json"
        elif isinstance(response_body, bytes):
            raw_body = response_body
        else:
            text_body = "" if response_body is None else str(response_body)
            raw_body = text_body.encode()

        if response_class is HTMLResponse and "content-type" not in response_headers:
            response_headers["content-type"] = "text/html; charset=utf-8"
        elif "content-type" not in response_headers:
            response_headers["content-type"] = "text/plain; charset=utf-8"

        await send(
            {
                "type": "http.response.start",
                "status": status_code,
                "headers": [
                    (header.encode(), value.encode()) for header, value in response_headers.items()
                ],
            }
        )
        await send({"type": "http.response.body", "body": raw_body})


class status:
    HTTP_200_OK = 200
    HTTP_201_CREATED = 201
    HTTP_400_BAD_REQUEST = 400
    HTTP_403_FORBIDDEN = 403
    HTTP_404_NOT_FOUND = 404
    HTTP_500_INTERNAL_SERVER_ERROR = 500


__all__ = ["FastAPI", "HTTPException", "Request", "status"]
