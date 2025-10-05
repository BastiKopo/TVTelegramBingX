"""Async REST client tailored for the BingX exchange."""
from __future__ import annotations

import asyncio
import time
from collections.abc import Mapping
from typing import Any

import httpx

from .auth import build_signature


class BingXRESTError(RuntimeError):
    """Raised when the BingX REST API returns an error response."""

    def __init__(self, message: str, *, status_code: int | None = None, payload: Any | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload


class BingXRESTClient:
    """Small httpx-based REST client that signs BingX requests."""

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        *,
        subaccount_id: str | None = None,
        base_url: str = "https://open-api.bingx.com",
        recv_window: int = 5_000,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_key = api_key
        self._api_secret = api_secret
        self._subaccount_id = subaccount_id
        self._recv_window = recv_window
        self._client = client or httpx.AsyncClient(base_url=base_url, timeout=httpx.Timeout(10.0, connect=5.0))
        self._time_offset = 0.0
        self._lock = asyncio.Lock()

    async def close(self) -> None:
        await self._client.aclose()

    async def time_sync(self) -> None:
        """Synchronise the client clock with the exchange server time."""

        async with self._lock:
            response = await self._client.get("/openApi/swap/v2/server/time")
            response.raise_for_status()
            payload = response.json()
            server_time = int(payload.get("serverTime", payload.get("timestamp", 0)))
            self._time_offset = server_time / 1000 - time.time()

    async def _signed_request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        data: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        if self._api_key is None or self._api_secret is None:  # pragma: no cover - guard
            raise BingXRESTError("API credentials missing")

        timestamp = int((time.time() + self._time_offset) * 1000)
        payload: dict[str, Any] = {"timestamp": timestamp, "recvWindow": self._recv_window}
        if params:
            payload.update(params)
        signature = build_signature(self._api_secret, payload)
        payload["signature"] = signature

        headers = {"X-BX-APIKEY": self._api_key}
        if self._subaccount_id:
            headers["X-BX-SUBACCOUNT-ID"] = self._subaccount_id

        request_params = payload if method.upper() == "GET" else None
        request_data = payload if method.upper() != "GET" else None
        if data:
            request_data = {**(request_data or {}), **data}

        response = await self._client.request(method.upper(), path, params=request_params, data=request_data, headers=headers)
        if response.status_code >= 400:
            raise BingXRESTError("BingX API request failed", status_code=response.status_code, payload=response.text)
        return response.json()

    async def get_positions(self, symbol: str | None = None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {}
        if symbol:
            params["symbol"] = symbol
        payload = await self._signed_request("GET", "/openApi/swap/v2/user/positions", params=params)
        return payload.get("data", payload.get("positions", []))

    async def get_all_orders(self, symbol: str | None = None) -> list[dict[str, Any]]:
        params = {"symbol": symbol} if symbol else None
        payload = await self._signed_request("GET", "/openApi/swap/v2/trade/allOrders", params=params)
        return payload.get("data", payload.get("orders", []))

    async def create_order(self, data: Mapping[str, Any]) -> dict[str, Any]:
        payload = await self._signed_request("POST", "/openApi/swap/v2/trade/order", data=data)
        return payload.get("data", payload)

    async def cancel_order(self, data: Mapping[str, Any]) -> dict[str, Any]:
        payload = await self._signed_request("POST", "/openApi/swap/v2/trade/cancel", data=data)
        return payload.get("data", payload)

    async def set_margin_mode(self, symbol: str, margin_mode: str) -> dict[str, Any]:
        payload = await self._signed_request(
            "POST",
            "/openApi/swap/v2/trade/marginType",
            data={"symbol": symbol, "marginType": margin_mode},
        )
        return payload.get("data", payload)

    async def set_leverage(self, symbol: str, leverage: int) -> dict[str, Any]:
        payload = await self._signed_request(
            "POST",
            "/openApi/swap/v2/trade/leverage",
            data={"symbol": symbol, "leverage": leverage},
        )
        return payload.get("data", payload)


__all__ = ["BingXRESTClient", "BingXRESTError"]
