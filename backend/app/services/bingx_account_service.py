"""Helpers for synchronising account preferences with BingX."""
from __future__ import annotations

from typing import Iterable

from ..config import Settings
from ..integrations.bingx import BingXRESTClient


class BingXAccountService:
    """Synchronise margin mode and leverage preferences with the exchange."""

    def __init__(self, client: BingXRESTClient, settings: Settings) -> None:
        self._client = client
        self._settings = settings

    async def ensure_preferences(self, symbols: Iterable[str], margin_mode: str | None, leverage: int | None) -> None:
        target_margin = margin_mode or self._settings.default_margin_mode
        target_leverage = leverage or self._settings.default_leverage
        for symbol in symbols:
            await self._client.set_margin_mode(symbol, target_margin)
            await self._client.set_leverage(symbol, target_leverage)


__all__ = ["BingXAccountService"]
