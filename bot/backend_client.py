"""HTTP client facade used by the Telegram bot."""
from __future__ import annotations

from collections.abc import Sequence
from contextlib import asynccontextmanager
from typing import AsyncIterator

import httpx

from .models import BotState, SignalRead


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

    async def get_state(self) -> BotState:
        async with self.session() as client:
            response = await client.get("/bot/status")
            response.raise_for_status()
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

        async with self.session() as client:
            response = await client.post("/bot/settings", json=payload)
            response.raise_for_status()
            return BotState.model_validate(response.json())

    async def fetch_recent_signals(self, limit: int = 5) -> Sequence[SignalRead]:
        async with self.session() as client:
            response = await client.get("/signals", params={"limit": limit})
            response.raise_for_status()
            items = response.json()
            return [SignalRead.model_validate(item) for item in items]

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


__all__ = ["BackendClient"]
