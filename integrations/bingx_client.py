"""Async client for interacting with the BingX REST API."""

from __future__ import annotations

import hashlib
import hmac
import time
from dataclasses import dataclass, field
from typing import Any, Mapping, MutableMapping

import httpx


class BingXClientError(RuntimeError):
    """Base exception raised when the BingX API returns an error."""


@dataclass
class BingXClient:
    """Thin asynchronous wrapper around the subset of the BingX REST API."""

    api_key: str
    api_secret: str
    base_url: str = "https://open-api.bingx.com"
    timeout: float = 10.0
    _client: httpx.AsyncClient | None = field(default=None, init=False, repr=False)

    async def __aenter__(self) -> "BingXClient":
        self._client = httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout)
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:  # type: ignore[override]
        if self._client:
            await self._client.aclose()
            self._client = None

    # ------------------------------------------------------------------
    # Public REST helpers
    # ------------------------------------------------------------------
    async def get_account_balance(self, currency: str | None = None) -> Any:
        """Return the account balance for the given currency (default USDT)."""

        params: dict[str, Any] = {}
        if currency:
            params["currency"] = currency
        data = await self._request("GET", "/openApi/swap/v2/user/balance", params=params)
        return data

    async def get_margin_summary(self, symbol: str | None = None) -> Any:
        """Return the margin overview for either the entire account or a symbol."""

        params: dict[str, Any] = {}
        if symbol:
            params["symbol"] = symbol
        data = await self._request("GET", "/openApi/swap/v2/user/margin", params=params)
        return data

    async def get_open_positions(self, symbol: str | None = None) -> Any:
        """Return the currently open positions."""

        params: dict[str, Any] = {}
        if symbol:
            params["symbol"] = symbol
        data = await self._request("GET", "/openApi/swap/v2/user/positions", params=params)
        return data

    async def get_leverage_settings(self, symbol: str | None = None) -> Any:
        """Return configured leverage values for the given symbol or entire account."""

        params: dict[str, Any] = {}
        if symbol:
            params["symbol"] = symbol
        data = await self._request("GET", "/openApi/swap/v2/user/leverage", params=params)
        return data

    # ------------------------------------------------------------------
    # Internal request helpers
    # ------------------------------------------------------------------
    async def _request(
        self, method: str, path: str, *, params: Mapping[str, Any] | None = None
    ) -> Any:
        if not self._client:
            raise BingXClientError(
                "HTTP client not initialised. Use 'async with BingXClient(...)' when calling the API."
            )

        signed_params = self._sign_parameters(params)
        headers = {"X-BX-APIKEY": self.api_key}

        response = await self._client.request(method, path, params=signed_params, headers=headers)

        try:
            payload = response.json()
        except ValueError as exc:  # pragma: no cover - defensive programming
            raise BingXClientError("Failed to decode BingX response as JSON") from exc

        if response.status_code != 200:
            raise BingXClientError(
                f"BingX API returned HTTP {response.status_code}: {payload!r}"
            )

        if isinstance(payload, Mapping):
            code = payload.get("code")
            if code not in (0, "0", None):
                message = payload.get("msg") or payload.get("message") or "Unknown error"
                raise BingXClientError(f"BingX API error {code}: {message}")
            return payload.get("data", payload)

        return payload

    def _sign_parameters(self, params: Mapping[str, Any] | None) -> MutableMapping[str, Any]:
        """Return parameters with the BingX HMAC SHA256 signature attached."""

        payload: MutableMapping[str, Any] = dict(params or {})
        timestamp = payload.get("timestamp") or str(int(time.time() * 1000))
        payload["timestamp"] = timestamp

        canonical_query = "&".join(f"{key}={payload[key]}" for key in sorted(payload))
        signature = hmac.new(
            self.api_secret.encode("utf-8"),
            canonical_query.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        payload["signature"] = signature
        return payload


__all__ = ["BingXClient", "BingXClientError"]
