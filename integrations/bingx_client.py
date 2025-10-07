"""Async client for interacting with the BingX REST API."""

from __future__ import annotations

import hashlib
import hmac
import time
from dataclasses import dataclass, field
from typing import Any, Mapping, MutableMapping
from urllib.parse import quote, urlencode

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
    recv_window: int | None = 30_000
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
    @staticmethod
    def _normalise_symbol(symbol: str) -> str:
        """Return a BingX compatible trading symbol."""

        text = symbol.strip().upper()
        if not text:
            return text

        # Remove potential broker prefixes while keeping anything after the last colon.
        if ":" in text:
            text = text.rsplit(":", 1)[-1]

        # Normalise common separators to the BingX ``AAA-BBB`` notation.
        for separator in ("/", "_"):
            if separator in text:
                text = text.replace(separator, "-")

        if "-" in text:
            parts = [segment for segment in text.split("-") if segment]
            if len(parts) >= 2:
                return f"{parts[0]}-{parts[1]}"
            return text

        for quote in ("USDT", "USDC"):
            if text.endswith(quote) and len(text) > len(quote):
                base = text[: -len(quote)]
                return f"{base}-{quote}"

        return text

    async def get_account_balance(self, currency: str | None = None) -> Any:
        """Return the account balance for the given currency (default USDT)."""

        params: dict[str, Any] = {}
        if currency:
            params["currency"] = currency
        data = await self._request_with_fallback(
            "GET",
            self._swap_paths("user/balance", "user/getBalance"),
            params=params,
        )
        return data

    async def get_margin_summary(self, symbol: str | None = None) -> Any:
        """Return the margin overview for either the entire account or a symbol."""

        params: dict[str, Any] = {}
        if symbol:
            params["symbol"] = self._normalise_symbol(symbol)
        data = await self._request_with_fallback(
            "GET",
            self._swap_paths("user/margin", "user/getMargin"),
            params=params,
        )
        return data

    async def get_open_positions(self, symbol: str | None = None) -> Any:
        """Return the currently open positions."""

        params: dict[str, Any] = {}
        if symbol:
            params["symbol"] = self._normalise_symbol(symbol)
        data = await self._request_with_fallback(
            "GET",
            self._swap_paths(
                "user/positions",
                "user/getPositions",
                "user/getPosition",
            ),
            params=params,
        )
        return data

    async def get_leverage_settings(self, symbol: str | None = None) -> Any:
        """Return configured leverage values for the given symbol or entire account."""

        params: dict[str, Any] = {}
        if symbol:
            params["symbol"] = self._normalise_symbol(symbol)
        data = await self._request_with_fallback(
            "GET",
            self._swap_paths(
                "user/leverage",
                "user/getLeverage",
                "trade/leverage",
            ),
            params=params,
        )
        return data

    async def place_order(
        self,
        *,
        symbol: str,
        side: str,
        position_side: str | None = None,
        quantity: float,
        order_type: str = "MARKET",
        price: float | None = None,
        margin_mode: str | None = None,
        margin_coin: str | None = None,
        leverage: float | None = None,
        reduce_only: bool | None = None,
        client_order_id: str | None = None,
    ) -> Any:
        """Place an order using the BingX trading endpoint."""

        params: MutableMapping[str, Any] = {
            "symbol": self._normalise_symbol(symbol),
            "side": side,
            "type": order_type,
            "quantity": quantity,
        }

        if position_side is not None:
            params["positionSide"] = position_side
        if price is not None:
            params["price"] = price
        if margin_mode is not None:
            params["marginType"] = margin_mode
        if margin_coin is not None:
            params["marginCoin"] = margin_coin
        if leverage is not None:
            params["leverage"] = leverage
        if reduce_only is not None:
            params["reduceOnly"] = "true" if reduce_only else "false"
        if client_order_id is not None:
            params["clientOrderId"] = client_order_id

        return await self._request_with_fallback(
            "POST",
            self._swap_paths("trade/order"),
            params=params,
        )

    async def set_margin_type(
        self,
        *,
        symbol: str,
        margin_mode: str,
        margin_coin: str | None = None,
    ) -> Any:
        """Configure the margin mode for a particular symbol."""

        params: MutableMapping[str, Any] = {
            "symbol": self._normalise_symbol(symbol),
            "marginType": margin_mode,
        }

        if margin_coin:
            params["marginCoin"] = margin_coin

        return await self._request_with_fallback(
            "POST",
            self._swap_paths("user/marginType", "user/setMarginType", "trade/marginType"),
            params=params,
        )

    async def set_leverage(
        self,
        *,
        symbol: str,
        leverage: float,
        margin_mode: str | None = None,
        margin_coin: str | None = None,
    ) -> Any:
        """Configure the leverage for a symbol."""

        params: MutableMapping[str, Any] = {
            "symbol": self._normalise_symbol(symbol),
            "leverage": leverage,
        }

        if margin_mode is not None:
            params["marginType"] = margin_mode
        if margin_coin is not None:
            params["marginCoin"] = margin_coin

        return await self._request_with_fallback(
            "POST",
            self._swap_paths("user/leverage", "user/setLeverage", "trade/leverage"),
            params=params,
        )

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

        query_string = self._sign_parameters(params)
        headers = {"X-BX-APIKEY": self.api_key}

        url = path
        if query_string:
            url = f"{path}?{query_string}"

        response = await self._client.request(method, url, headers=headers)

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

    async def _request_with_fallback(
        self,
        method: str,
        paths: tuple[str, ...],
        *,
        params: Mapping[str, Any] | None = None,
    ) -> Any:
        """Attempt the request using multiple API paths to support BingX upgrades."""

        last_error: BingXClientError | None = None

        for path in paths:
            try:
                return await self._request(method, path, params=params)
            except BingXClientError as exc:
                if not self._is_missing_api_error(exc):
                    raise
                last_error = exc
                continue

        if last_error is not None:
            raise last_error

        raise BingXClientError("No API paths provided for request")

    @staticmethod
    def _swap_paths(*endpoints: str) -> tuple[str, ...]:
        """Return swap API versions to try for the given endpoint."""

        versions = ("v3", "v2", "v1")
        if not endpoints:
            endpoints = ("user/balance",)

        return tuple(
            f"/openApi/swap/{version}/{endpoint}"
            for endpoint in endpoints
            for version in versions
        )

    @staticmethod
    def _is_missing_api_error(error: BingXClientError) -> bool:
        """Return True if the error indicates that the endpoint no longer exists."""

        message = str(error).lower()
        return "100400" in message and "api" in message and "not exist" in message

    def _sign_parameters(self, params: Mapping[str, Any] | None) -> str:
        """Return the canonical query string with an attached HMAC signature."""

        def _stringify(value: Any) -> str:
            if isinstance(value, bool):
                return "true" if value else "false"
            if isinstance(value, float):
                formatted = f"{value:.16f}".rstrip("0").rstrip(".")
                return formatted or "0"
            return str(value)

        payload: dict[str, str] = {
            str(key): _stringify(value)
            for key, value in (params or {}).items()
            if value is not None
        }

        if "timestamp" not in payload:
            payload["timestamp"] = _stringify(int(time.time() * 1000))

        if "recvWindow" not in payload and self.recv_window:
            payload["recvWindow"] = _stringify(self.recv_window)

        sorted_items = sorted(payload.items())

        canonical_query = urlencode(
            sorted_items,
            safe="-_.~",
            quote_via=quote,
        )

        signature = hmac.new(
            self.api_secret.encode("utf-8"),
            canonical_query.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        return f"{canonical_query}&signature={signature}"


__all__ = ["BingXClient", "BingXClientError"]
