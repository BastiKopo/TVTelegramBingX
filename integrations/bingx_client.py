"""Async client for interacting with the BingX REST API."""

from __future__ import annotations

import hashlib
import hmac
import time
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation, ROUND_DOWN
from typing import Any, Mapping, MutableMapping
from urllib.parse import quote, urlencode

try:  # pragma: no cover - optional dependency for test environments
    import httpx
except ModuleNotFoundError:  # pragma: no cover - fallback for tests without httpx
    httpx = None  # type: ignore[assignment]


class BingXClientError(RuntimeError):
    """Base exception raised when the BingX API returns an error."""


def calc_order_qty(
    price: float,
    margin_usdt: float,
    leverage: float,
    step_size: float,
    min_qty: float,
) -> float:
    """Return a quantity respecting the exchange filters.

    The TradingView alerts configure a *margin_usdt* budget which gets scaled by
    *leverage*.  BingX enforces a minimum quantity as well as a tick size for the
    quantity.  The result therefore needs to be rounded down to the next valid
    tick size while still respecting the minimum quantity.  A :class:`ValueError`
    is raised if the provided configuration would lead to an invalid order.
    """

    if price <= 0:
        raise ValueError("Price must be greater than zero to calculate the order quantity.")
    if margin_usdt <= 0:
        raise ValueError("Margin must be greater than zero to calculate the order quantity.")
    if leverage <= 0:
        raise ValueError("Leverage must be greater than zero to calculate the order quantity.")
    if step_size <= 0:
        raise ValueError("Step size must be greater than zero to calculate the order quantity.")
    if min_qty < 0:
        raise ValueError("Minimum quantity cannot be negative.")

    try:
        price_dec = Decimal(str(price))
        margin_dec = Decimal(str(margin_usdt))
        leverage_dec = Decimal(str(leverage))
        step_dec = Decimal(str(step_size))
        min_qty_dec = Decimal(str(min_qty))
    except InvalidOperation as exc:  # pragma: no cover - defensive
        raise ValueError("Invalid numeric value provided for quantity calculation") from exc

    notional_value = (margin_dec * leverage_dec) / price_dec
    if notional_value <= 0:
        raise ValueError("Computed order quantity is not positive.")

    steps = (notional_value / step_dec).to_integral_value(rounding=ROUND_DOWN)
    quantity = steps * step_dec

    if quantity < min_qty_dec:
        quantity = min_qty_dec

    return float(quantity)


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
        if httpx is None:  # pragma: no cover - dependency guard for optional install
            raise BingXClientError("The 'httpx' package is required to use BingXClient")

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

    async def get_mark_price(self, symbol: str) -> float:
        """Return the current mark price for *symbol*."""

        params = {"symbol": self._normalise_symbol(symbol)}
        payload = await self._request_with_fallback(
            "GET",
            self._swap_paths(
                "market/markPrice",
                "market/getMarkPrice",
                "market/price",
            ),
            params=params,
        )

        price = self._extract_float(payload, "price", "markPrice", "mark_price")
        if price is None:
            raise BingXClientError(f"Unable to determine mark price for {symbol!r}: {payload!r}")

        return price

    async def get_symbol_filters(self, symbol: str) -> dict[str, float]:
        """Return quantity filters for *symbol*.

        The structure of the BingX response has changed a few times historically
        which is why the parser accepts several shapes.  The result always
        contains ``min_qty`` and ``step_size`` keys.
        """

        params = {"symbol": self._normalise_symbol(symbol)}
        payload = await self._request_with_fallback(
            "GET",
            self._swap_paths(
                "market/symbol-config",
                "market/getSymbol",
                "market/detail",
            ),
            params=params,
        )

        filters: Mapping[str, Any] | None = None
        if isinstance(payload, Mapping):
            if "filters" in payload and isinstance(payload["filters"], Mapping):
                filters = payload["filters"]
            elif "data" in payload and isinstance(payload["data"], Mapping):
                filters = payload["data"]
        elif isinstance(payload, list) and payload:
            candidate = payload[0]
            if isinstance(candidate, Mapping):
                filters = candidate.get("filters") if isinstance(candidate.get("filters"), Mapping) else candidate

        if not isinstance(filters, Mapping):
            raise BingXClientError(f"Unexpected filters payload for {symbol!r}: {payload!r}")

        min_qty = self._extract_float(filters, "minQty", "min_qty", "min_quantity")
        step_size = self._extract_float(filters, "stepSize", "step_size", "qty_step", "qtyStep")

        if min_qty is None or step_size is None:
            raise BingXClientError(f"Quantity filters missing for {symbol!r}: {filters!r}")

        return {"min_qty": min_qty, "step_size": step_size}

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
        side: str | None = None,
        position_side: str | None = None,
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
        if side is not None:
            params["side"] = side
        if position_side is not None:
            params["positionSide"] = position_side

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
    def _extract_float(payload: Any, *keys: str) -> float | None:
        """Return the first parsable float from *payload* using *keys*."""

        values: list[Any] = []
        if isinstance(payload, Mapping):
            values.extend(payload.get(key) for key in keys if key in payload)
            nested = payload.get("data")
            if isinstance(nested, Mapping):
                values.extend(nested.get(key) for key in keys if key in nested)
        elif isinstance(payload, list):
            for item in payload:
                if isinstance(item, Mapping):
                    candidate = BingXClient._extract_float(item, *keys)
                    if candidate is not None:
                        return candidate

        for value in values:
            try:
                return float(value)
            except (TypeError, ValueError):
                continue

        return None

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
            if isinstance(value, (float, Decimal)):
                # Convert via ``Decimal`` to preserve the literal precision from TradingView
                # alerts instead of the binary float representation (e.g. 1.95 -> 1.9499...).
                try:
                    decimal_value = value if isinstance(value, Decimal) else Decimal(str(value))
                except InvalidOperation:  # pragma: no cover - defensive guard
                    return str(value)

                text = format(decimal_value.normalize(), "f").rstrip("0").rstrip(".")
                return text or "0"
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
