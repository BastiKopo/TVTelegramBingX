"""Async client for interacting with the BingX REST API."""

from __future__ import annotations

import hashlib
import hmac
import logging
import math
import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Mapping, MutableMapping
from urllib.parse import quote, urlencode

try:  # pragma: no cover - optional dependency for test environments
    import httpx
except ModuleNotFoundError:  # pragma: no cover - fallback for tests without httpx
    httpx = None  # type: ignore[assignment]

LOGGER = logging.getLogger(__name__)
def _round_up(x: float, step: float) -> float:
    if step <= 0:
        return x
    return math.ceil(x / step) * step


def _round_down(x: float, step: float) -> float:
    if step <= 0:
        return x
    return math.floor(x / step) * step


def calc_order_qty(
    price: float,
    margin_usdt: float,
    leverage: int,
    step_size: float,
    min_qty: float,
    min_notional: float | None = None,
) -> float:
    """Qty aus Margin * Leverage. Danach Step- und Notional-Filter berücksichtigen."""

    if price <= 0:
        raise ValueError("Ungültiger Preis")
    if margin_usdt < 0:
        raise ValueError("Margin darf nicht negativ sein")
    if leverage <= 0:
        raise ValueError("Leverage muss größer als 0 sein")

    target_nominal = margin_usdt * leverage
    raw_qty = target_nominal / price

    qty = max(min_qty, _round_up(raw_qty, step_size))

    if min_notional is not None and qty * price < min_notional:
        qty = max(qty, _round_up(min_notional / price, step_size))

    if qty * price > target_nominal:
        qty_down = _round_down(target_nominal / price, step_size)
        if qty_down >= min_qty and (
            min_notional is None or qty_down * price >= min_notional
        ):
            qty = qty_down
        else:
            min_required = max(min_qty, (min_notional or 0) / price)
            needed_margin = (min_required * price) / max(1, leverage)
            raise ValueError(
                f"Margin zu klein: Mindestens ~{needed_margin:.4f} USDT nötig (bei {leverage}x)."
            )

    return qty


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
    symbol_filters_ttl: float = 300.0
    _client: httpx.AsyncClient | None = field(default=None, init=False, repr=False)
    _filters_cache: MutableMapping[str, tuple[float, dict[str, float]]] = field(
        default_factory=dict, init=False, repr=False
    )

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
            self._swap_paths(
                "user/balance",
                "user/getBalance",
            ),
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
            self._swap_paths(
                "user/margin",
                "user/getMargin",
            ),
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

        normalised_symbol = self._normalise_symbol(symbol)
        now = time.monotonic()

        if self.symbol_filters_ttl > 0:
            cached = self._filters_cache.get(normalised_symbol)
            if cached:
                cached_at, payload = cached
                if now - cached_at < self.symbol_filters_ttl:
                    return dict(payload)
                self._filters_cache.pop(normalised_symbol, None)

        params = {"symbol": normalised_symbol}
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
        min_notional = self._extract_float(filters, "minNotional", "min_notional", "notional")

        if min_qty is None or step_size is None:
            raise BingXClientError(f"Quantity filters missing for {symbol!r}: {filters!r}")

        result = {"min_qty": min_qty, "step_size": step_size}
        if min_notional is not None:
            result["min_notional"] = min_notional

        if self.symbol_filters_ttl > 0:
            self._filters_cache[normalised_symbol] = (now, dict(result))

        return result

    def clear_symbol_filters_cache(self, symbol: str | None = None) -> None:
        """Invalidate cached symbol filter data."""

        if symbol is None:
            self._filters_cache.clear()
            return

        self._filters_cache.pop(self._normalise_symbol(symbol), None)

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
            params["marginMode"] = margin_mode
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
            self._swap_paths(
                "trade/order",
            ),
            params=params,
        )

    async def place_futures_market_order(
        self,
        *,
        symbol: str,
        side: str,
        qty: float,
        reduce_only: bool = False,
        position_side: str | None = None,
        client_order_id: str | None = None,
    ) -> Any:
        """Place a futures market order without falling back to spot endpoints."""

        params: MutableMapping[str, Any] = {
            "symbol": self._normalise_symbol(symbol),
            "side": side.upper(),
            "type": "MARKET",
            "quantity": qty,
        }

        if position_side:
            params["positionSide"] = position_side
        if reduce_only:
            params["reduceOnly"] = "true"
        if client_order_id:
            params["clientOrderId"] = client_order_id

        LOGGER.info("Placing futures market order: %s", params)

        return await self._request_with_fallback(
            "POST",
            self._swap_paths(
                "trade/order",
            ),
            params=params,
        )

    async def get_position_mode(self) -> bool:
        """Return ``True`` when the account is configured for hedge mode."""

        payload = await self._request_with_fallback(
            "GET",
            self._swap_paths(
                "user/positionSide/dual",
                "trade/positionSide/dual",
            ),
        )

        if isinstance(payload, Mapping):
            containers = [payload]
            nested = payload.get("data")
            if isinstance(nested, Mapping):
                containers.append(nested)

            for container in containers:
                for key in ("dualSidePosition", "dualSide", "isDualSide", "positionMode"):
                    value = self._coerce_bool(container.get(key))
                    if value is not None:
                        return value

            raise BingXClientError(
                "BingX lieferte keinen gültigen Positionsmodus in der Antwort."
            )

        raise BingXClientError(
            "BingX lieferte keinen gültigen Positionsmodus in der Antwort."
        )

    async def set_margin_type(
        self,
        *,
        symbol: str,
        isolated: bool | None = None,
        margin_mode: str | None = None,
        margin_coin: str | None = None,
    ) -> Any:
        """Configure the margin mode for a particular symbol."""

        mode = margin_mode
        if mode is None:
            if isolated is None:
                raise ValueError("Either 'isolated' or 'margin_mode' must be provided.")
            mode = "ISOLATED" if isolated else "CROSSED"

        params: MutableMapping[str, Any] = {
            "symbol": self._normalise_symbol(symbol),
            "marginMode": mode,
        }

        if margin_coin:
            params["marginCoin"] = margin_coin

        return await self._request_with_fallback(
            "POST",
            self._swap_paths(
                "trade/setMarginMode",
                "trade/marginType",
                "user/marginType",
                "user/setMarginType",
            ),
            params=params,
        )

    async def set_leverage(
        self,
        *,
        symbol: str,
        lev_long: int | float | None = None,
        lev_short: int | float | None = None,
        hedge: bool | None = None,
        leverage: float | None = None,
        margin_mode: str | None = None,
        margin_coin: str | None = None,
        side: str | None = None,
        position_side: str | None = None,
        leverage_long: float | None = None,
        leverage_short: float | None = None,
        isolated: bool | None = None,
        hedge_mode: bool | None = None,
    ) -> Any:
        """Configure leverage for a symbol or both position sides in hedge mode."""

        if leverage is not None:
            return await self._set_single_leverage(
                symbol=symbol,
                leverage=leverage,
                margin_mode=margin_mode,
                margin_coin=margin_coin,
                side=side,
                position_side=position_side,
            )

        if leverage_long is not None or leverage_short is not None:
            lev_long = leverage_long if leverage_long is not None else lev_long
            lev_short = leverage_short if leverage_short is not None else lev_short

        if lev_long is None and lev_short is None:
            raise ValueError(
                "Either 'leverage' or both 'lev_long' and 'lev_short' must be provided."
            )

        if lev_long is None:
            lev_long = lev_short
        if lev_short is None:
            lev_short = lev_long

        if lev_long is None or lev_short is None:
            raise ValueError("Unable to determine leverage values for both sides.")

        if isolated is not None and margin_mode is None:
            margin_mode = "ISOLATED" if isolated else "CROSSED"

        if margin_mode is not None:
            await self.set_margin_type(
                symbol=symbol,
                margin_mode=margin_mode,
                margin_coin=margin_coin,
            )

        if hedge is None:
            hedge = hedge_mode if hedge_mode is not None else True

        if hedge:
            await self.set_position_mode(True)
            responses: dict[str, Any] = {}
            responses["long"] = await self._set_single_leverage(
                symbol=symbol,
                leverage=lev_long,
                margin_coin=margin_coin,
                side="BUY",
                position_side="LONG",
            )
            responses["short"] = await self._set_single_leverage(
                symbol=symbol,
                leverage=lev_short,
                margin_coin=margin_coin,
                side="SELL",
                position_side="SHORT",
            )
            return responses

        await self.set_position_mode(False)
        return await self._set_single_leverage(
            symbol=symbol,
            leverage=lev_long,
            margin_mode=margin_mode,
            margin_coin=margin_coin,
            side=side,
            position_side=position_side,
        )

    async def _set_single_leverage(
        self,
        *,
        symbol: str,
        leverage: float,
        margin_mode: str | None = None,
        margin_coin: str | None = None,
        side: str | None = None,
        position_side: str | None = None,
    ) -> Any:
        """Configure the leverage for a single position side."""

        params: MutableMapping[str, Any] = {
            "symbol": self._normalise_symbol(symbol),
            "leverage": leverage,
        }

        if margin_mode is not None:
            params["marginMode"] = margin_mode
        if margin_coin is not None:
            params["marginCoin"] = margin_coin
        if side is not None:
            params["side"] = side
        if position_side is not None:
            params["positionSide"] = position_side

        return await self._request_with_fallback(
            "POST",
            self._swap_paths(
                "trade/setLeverage",
                "trade/leverage",
                "user/leverage",
                "user/setLeverage",
            ),
            params=params,
        )

    async def set_position_mode(self, hedge: bool) -> Any:
        """Enable or disable hedge mode on the account."""

        return await self._request_with_fallback(
            "POST",
            self._swap_paths(
                "user/positionSide/dual",
                "trade/positionSide/dual",
            ),
            params={"dualSidePosition": "true" if hedge else "false"},
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

        if not paths:
            raise BingXClientError("No API paths provided for request")

        last_error: BingXClientError | None = None

        for path in paths:
            LOGGER.debug("Attempting BingX request %s %s", method, path)
            try:
                payload = await self._request(method, path, params=params)
            except BingXClientError as exc:
                if not self._is_missing_api_error(exc):
                    raise
                LOGGER.warning(
                    "BingX endpoint unavailable (%s %s): %s", method, path, exc
                )
                last_error = exc
                continue

            LOGGER.info("BingX request succeeded via %s %s", method, path)
            return payload

        assert last_error is not None  # ``paths`` is not empty here
        raise last_error

    @staticmethod
    def _swap_paths(*endpoints: str) -> tuple[str, ...]:
        """Return the canonical Swap V2 API paths for the given endpoint."""

        if not endpoints:
            endpoints = ("user/balance",)

        # Regardless of the legacy parameters we only target the officially
        # supported Swap V2 REST layout under ``/openApi`` with a fallback that
        # swaps the version and prefix segments.  This keeps the client aligned
        # with the current BingX documentation while remaining resilient when
        # BingX temporarily flips the order of ``swap`` and ``v2``.
        paths: list[str] = []
        for endpoint in endpoints:
            paths.append(f"/openApi/swap/v2/{endpoint}")
            paths.append(f"/openApi/v2/swap/{endpoint}")

        return tuple(dict.fromkeys(paths))

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

    @staticmethod
    def _coerce_bool(value: Any) -> bool | None:
        """Best effort conversion of BingX truthy flags to Python booleans."""

        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            if value == 1:
                return True
            if value == 0:
                return False
        if isinstance(value, str):
            token = value.strip().lower()
            if token in {"true", "1", "yes", "y", "on"}:
                return True
            if token in {"false", "0", "no", "n", "off"}:
                return False
        return None

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
