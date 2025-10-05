"""HTTP client facade used by the Telegram bot."""
from __future__ import annotations

import time
from collections.abc import Sequence
from contextlib import asynccontextmanager, contextmanager
from typing import AsyncIterator

import httpx

from .models import BotState, SignalRead
from .metrics import observe_backend_request

try:  # pragma: no cover - optional instrumentation
    from opentelemetry import metrics as _metrics, trace as _trace
    from opentelemetry.trace import Status, StatusCode
except Exception:  # pragma: no cover - otel not installed
    _metrics = None
    _trace = None
    Status = None
    StatusCode = None

if _trace is not None:  # pragma: no branch - guard instrumentation
    _tracer = _trace.get_tracer("tvtelegrambingx.bot.backend_client")
else:  # pragma: no cover - otel disabled
    _tracer = None

if _metrics is not None:  # pragma: no branch - guard instrumentation
    _meter = _metrics.get_meter("tvtelegrambingx.bot.backend_client")
    _request_counter = _meter.create_counter(
        "bot_backend_requests_total",
        description="Number of HTTP requests issued by the Telegram bot",
    )
    _request_latency = _meter.create_histogram(
        "bot_backend_request_duration_seconds",
        unit="s",
        description="Latency of HTTP calls from the bot to the backend",
    )
else:  # pragma: no cover - otel disabled
    _request_counter = None
    _request_latency = None


@contextmanager
def _span(name: str, attributes: dict[str, object] | None = None):
    if _tracer is None:  # pragma: no cover - otel disabled
        yield None
        return
    with _tracer.start_as_current_span(name) as span:
        if attributes:
            for key, value in attributes.items():
                span.set_attribute(key, value)
        yield span


class BackendClient:
    """Thin wrapper around the backend HTTP API."""

    def __init__(self, base_url: str, timeout: float = 10.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._client: httpx.AsyncClient | None = None

    @asynccontextmanager
    async def session(self) -> AsyncIterator[httpx.AsyncClient]:
        if self._client is None:
            self._client = httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout)
        try:
            yield self._client
        finally:
            # connection pooling is desired so we keep the client open
            pass

    async def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        start = time.perf_counter()
        attributes = {"http.method": method, "http.route": path}
        async with self.session() as client:
            with _span(f"BackendClient.{method.lower()}", attributes) as span:
                response = await client.request(method, path, **kwargs)
                if span is not None:  # pragma: no cover - otel disabled
                    span.set_attribute("http.status_code", response.status_code)
                duration = time.perf_counter() - start
                if _request_latency is not None:
                    _request_latency.record(duration, attributes={"method": method, "path": path})
                if _request_counter is not None:
                    _request_counter.add(1, attributes={
                        "method": method,
                        "path": path,
                        "status": str(response.status_code),
                    })
                observe_backend_request(method, path, response.status_code, duration)
                try:
                    response.raise_for_status()
                except httpx.HTTPStatusError as exc:  # pragma: no cover - error path
                    if span is not None and Status is not None and StatusCode is not None:
                        span.set_status(Status(StatusCode.ERROR, exc.response.reason_phrase or exc.message))
                        span.record_exception(exc)
                    raise
                return response

    async def get_state(self) -> BotState:
        response = await self._request("GET", "/bot/status")
        return BotState.model_validate(response.json())

    async def update_state(
        self,
        *,
        auto_trade_enabled: bool | None = None,
        manual_confirmation_required: bool | None = None,
        margin_mode: str | None = None,
        leverage: int | None = None,
    ) -> BotState:
        payload: dict[str, object] = {}
        if auto_trade_enabled is not None:
            payload["auto_trade_enabled"] = auto_trade_enabled
        if manual_confirmation_required is not None:
            payload["manual_confirmation_required"] = manual_confirmation_required
        if margin_mode is not None:
            payload["margin_mode"] = margin_mode
        if leverage is not None:
            payload["leverage"] = leverage

        response = await self._request("POST", "/bot/settings", json=payload)
        return BotState.model_validate(response.json())

    async def fetch_recent_signals(self, limit: int = 5) -> Sequence[SignalRead]:
        response = await self._request("GET", "/signals", params={"limit": limit})
        items = response.json()
        return [SignalRead.model_validate(item) for item in items]

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


__all__ = ["BackendClient"]
