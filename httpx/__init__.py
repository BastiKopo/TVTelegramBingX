"""Minimal stub implementation of the :mod:`httpx` API used in tests."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Mapping, Optional

class HTTPStatusError(Exception):
    """Raised when an HTTP response indicates an error."""


class Request:
    """Lightweight representation of an HTTP request."""

    def __init__(
        self,
        method: str,
        url: str,
        *,
        path: str,
        headers: Optional[Mapping[str, str]] = None,
        params: Optional[Mapping[str, Any]] = None,
        data: Optional[Mapping[str, Any]] = None,
    ) -> None:
        self.method = method.upper()
        self._url = url
        self.path = path
        self.headers: dict[str, str] = dict(headers or {})
        self.params: dict[str, Any] = dict(params or {})
        self.data: dict[str, Any] = dict(data or {})

    @property
    def url(self) -> "_URL":
        return _URL(self._url, self.params)


class Response:
    """Simplified HTTP response container."""

    def __init__(self, status_code: int, *, json: Any | None = None, text: str | None = None) -> None:
        self.status_code = status_code
        self._json = json
        self._text = text or ("" if json is None else str(json))

    def json(self) -> Any:
        return self._json

    @property
    def text(self) -> str:
        return self._text

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise HTTPStatusError(f"Request failed with status {self.status_code}")


class _URL:
    def __init__(self, value: str, params: Mapping[str, Any]):
        self._value = value
        self.params = params

    def __str__(self) -> str:  # pragma: no cover - debugging helper
        if not self.params:
            return self._value
        query = "&".join(f"{key}={value}" for key, value in self.params.items())
        return f"{self._value}?{query}"


class MockTransport:
    """Transport that calls a provided handler coroutine."""

    def __init__(self, handler: Callable[[Request], Awaitable[Response] | Response]) -> None:
        self._handler = handler

    async def handle(self, request: Request) -> Response:
        result = self._handler(request)
        if asyncio.iscoroutine(result):
            result = await result
        return result


@dataclass
class Timeout:
    timeout: float
    connect: float | None = None


class ASGITransport(MockTransport):
    """Simple transport using FastAPI's synchronous TestClient."""

    def __init__(self, app, lifespan: str = "auto") -> None:
        from fastapi.testclient import TestClient  # imported lazily to avoid circular dependency

        self._client = TestClient(app, base_url="http://test")
        self._client.__enter__()
        super().__init__(self._dispatch)

    async def _dispatch(self, request: Request) -> Response:
        response = self._client.request(
            request.method,
            request.path,
            headers=request.headers,
            params=request.params,
            json=request.data if request.data else None,
        )
        try:
            payload = response.json()
        except ValueError:
            payload = None
        return Response(response.status_code, json=payload, text=response.text)

    def close(self) -> None:
        self._client.__exit__(None, None, None)


class AsyncClient:
    """Very small subset of :class:`httpx.AsyncClient`."""

    def __init__(self, *, transport: MockTransport | None = None, base_url: str = "", timeout: Timeout | None = None) -> None:
        self._transport = transport
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    async def request(
        self,
        method: str,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        data: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Response:
        full_url = f"{self._base_url}{url}" if url.startswith("/") else url
        path = url if url.startswith("/") else full_url
        request = Request(method, full_url, path=path, headers=headers, params=params, data=data)
        if self._transport is None:
            raise RuntimeError("httpx stub cannot perform real network requests")
        return await self._transport.handle(request)

    async def get(self, url: str, *, params: Mapping[str, Any] | None = None, headers: Mapping[str, str] | None = None) -> Response:
        return await self.request("GET", url, params=params, headers=headers)

    async def aclose(self) -> None:
        if hasattr(self._transport, "close"):
            result = self._transport.close()
            if asyncio.iscoroutine(result):
                await result

    async def __aenter__(self) -> "AsyncClient":  # pragma: no cover - convenience helper
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:  # pragma: no cover - convenience helper
        await self.aclose()


__all__ = [
    "ASGITransport",
    "AsyncClient",
    "HTTPStatusError",
    "MockTransport",
    "Request",
    "Response",
    "Timeout",
]
