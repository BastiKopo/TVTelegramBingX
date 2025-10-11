"""Async client for interacting with the BingX REST API."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import random
import re
import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Mapping, MutableMapping
from urllib.parse import quote, urlencode

try:  # pragma: no cover - optional dependency for test environments
    import httpx
except ModuleNotFoundError:  # pragma: no cover - fallback for tests without httpx
    httpx = None  # type: ignore[assignment]

from services.symbols import SymbolValidationError, normalize_symbol
from services.sizing import qty_from_margin_usdt

from .bingx_constants import (
    BINGX_BASE,
    PATH_ORDER,
    PATH_QUOTE_CONTRACTS,
    PATH_SET_LEVERAGE,
    PATH_SET_MARGIN,
    PATH_USER_BALANCE,
    PATH_USER_POSITIONS,
)
from .bingx_errors import format_bingx_error
from .bingx_guards import assert_bingx_base, assert_order_path

LOGGER = logging.getLogger(__name__)

_SWAP_V2_PREFIX = "/openApi/swap/v2/"


def _pow10(power: int) -> str:
    """Return ``10^-power`` as a decimal string without exponent notation."""

    if power < 0:
        raise ValueError("power must be non-negative")
    if power == 0:
        return "1"

    # ``format`` avoids scientific notation while keeping significant digits.
    return format(Decimal(1) / (Decimal(10) ** power), "f")


def _as_decimal(value: Any) -> Decimal | None:
    """Coerce *value* into :class:`~decimal.Decimal` if possible."""

    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    if isinstance(value, str):
        token = value.strip()
        if not token:
            return None
        try:
            return Decimal(token)
        except ArithmeticError:
            return None
    return None


def _decimal_to_string(value: Decimal) -> str:
    """Return a canonical decimal string for *value* without exponent notation."""

    token = format(value.normalize(), "f")
    if "." in token:
        token = token.rstrip("0").rstrip(".")
    return token or "0"


def normalize_contract_filters(contract: Mapping[str, Any]) -> dict[str, Any]:
    """Normalise the BingX contract payload to the bot's filter schema."""

    step_raw = contract.get("stepSize")
    if not step_raw:
        quantity_precision_raw = contract.get("quantityPrecision")
        quantity_precision = None
        if quantity_precision_raw is not None:
            try:
                quantity_precision = int(quantity_precision_raw)
            except (TypeError, ValueError):
                quantity_precision = None
        if quantity_precision is not None:
            step_raw = _pow10(quantity_precision)
        elif contract.get("size") is not None:
            step_decimal = _as_decimal(contract.get("size"))
            if step_decimal is not None:
                step_raw = _decimal_to_string(step_decimal)
    else:
        step_decimal = _as_decimal(step_raw)
        if step_decimal is not None:
            step_raw = _decimal_to_string(step_decimal)

    if not step_raw:
        symbol = contract.get("symbol") or contract.get("symbolName")
        raise BingXClientError(
            f"missing stepSize/quantityPrecision/size in {symbol!r}"
        )

    step_decimal = _as_decimal(step_raw)
    if step_decimal is None:
        raise BingXClientError(f"invalid stepSize value {step_raw!r}")

    min_qty_decimal = _as_decimal(contract.get("tradeMinQuantity"))
    if min_qty_decimal is None or min_qty_decimal <= 0:
        min_qty_decimal = step_decimal

    tick_raw = contract.get("tickSize")
    if tick_raw:
        tick_decimal = _as_decimal(tick_raw)
        tick = (
            _decimal_to_string(tick_decimal)
            if tick_decimal is not None and tick_decimal > 0
            else None
        )
    else:
        tick_decimal = None
        price_precision_raw = contract.get("pricePrecision")
        price_precision = None
        if price_precision_raw is not None:
            try:
                price_precision = int(price_precision_raw)
            except (TypeError, ValueError):
                price_precision = None
        tick = _pow10(price_precision) if price_precision is not None else None

    if tick is None:
        tick = "0.01"
        tick_decimal = Decimal(tick)
    else:
        tick_decimal = _as_decimal(tick)
        if tick_decimal is None or tick_decimal <= 0:
            tick = "0.01"
            tick_decimal = Decimal(tick)

    price_precision_value: int | None = None
    price_precision_raw = contract.get("pricePrecision")
    if price_precision_raw is not None:
        try:
            price_precision_value = int(price_precision_raw)
        except (TypeError, ValueError):
            price_precision_value = None

    quantity_precision_value: int | None = None
    quantity_precision_raw = contract.get("quantityPrecision")
    if quantity_precision_raw is not None:
        try:
            quantity_precision_value = int(quantity_precision_raw)
        except (TypeError, ValueError):
            quantity_precision_value = None

    return {
        "stepSize": _decimal_to_string(step_decimal),
        "minQty": _decimal_to_string(min_qty_decimal),
        "tickSize": _decimal_to_string(tick_decimal),
        "pricePrecision": price_precision_value,
        "quantityPrecision": quantity_precision_value,
    }

_ERROR_HINTS = {
    "109414": "Hedge-Mode aktiv – bitte LONG/SHORT verwenden.",
    "101205": "Keine passende Position auf dieser Seite zu schließen.",
}

_RATE_LIMIT_TOKENS = {"too many", "limit", "frequency"}

def calc_order_qty(
    price: float,
    margin_usdt: float,
    leverage: int,
    step_size: float,
    min_qty: float,
    min_notional: float | None = None,
) -> float:
    """Qty aus Margin * Leverage mit Step-Size-Rundung."""

    step_token = format(step_size, "f").rstrip("0").rstrip(".") or "0"
    min_qty_token = (
        format(min_qty, "f").rstrip("0").rstrip(".")
        if min_qty > 0
        else None
    )
    min_notional_token = (
        format(min_notional, "f").rstrip("0").rstrip(".")
        if min_notional is not None and min_notional > 0
        else None
    )

    qty_text = qty_from_margin_usdt(
        str(margin_usdt),
        leverage,
        str(price),
        step_token,
        min_qty=min_qty_token,
        min_notional=min_notional_token,
    )
    return float(qty_text)


class BingXClientError(RuntimeError):
    """Base exception raised when the BingX API returns an error."""
@dataclass
class BingXClient:
    """Thin asynchronous wrapper around the subset of the BingX REST API."""

    api_key: str
    api_secret: str
    base_url: str = BINGX_BASE
    timeout: float = 10.0
    recv_window: int | None = 30_000
    symbol_filters_ttl: float = 300.0
    max_retries: int = 3
    _client: httpx.AsyncClient | None = field(default=None, init=False, repr=False)
    _filters_cache: MutableMapping[str, tuple[float, dict[str, float]]] = field(
        default_factory=dict, init=False, repr=False
    )

    def __post_init__(self) -> None:
        try:
            assert_bingx_base(self.base_url)
        except ValueError as exc:
            raise BingXClientError(str(exc)) from exc

        self.base_url = self.base_url.rstrip("/") or BINGX_BASE

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

        try:
            return normalize_symbol(symbol)
        except SymbolValidationError as exc:
            raise BingXClientError(str(exc)) from exc

    @staticmethod
    def _swap_v2_path(endpoint: str) -> str:
        """Return the canonical Swap V2 path for *endpoint*."""

        token = endpoint.strip().strip("/")
        if not token:
            token = "user/balance"
        if token.startswith("openApi/"):
            return f"/{token}"

        # ``endpoint`` may be an absolute path (``/openApi/…``) or shorthand
        # without the prefix.  Only append the Swap V2 prefix when it is
        # missing to avoid duplicating segments.
        return f"{_SWAP_V2_PREFIX}{token}"

    async def get_account_balance(self, currency: str | None = None) -> Any:
        """Return the account balance for the given currency (default USDT)."""

        params: dict[str, Any] = {}
        if currency:
            params["currency"] = currency
        data = await self._request_with_fallback(
            "GET",
            self._swap_paths(
                PATH_USER_BALANCE,
                "user/getBalance",
            ),
            params=params,
        )
        return data

    async def get_account_snapshot(self, symbol: str | None = None) -> Mapping[str, Any]:
        """Return a consolidated view of balance and open positions."""

        balance_task = asyncio.create_task(self.get_account_balance())
        positions_task = asyncio.create_task(self.get_open_positions(symbol=symbol))

        balance_payload, positions_payload = await asyncio.gather(
            balance_task, positions_task
        )

        wallet_balance = self._extract_wallet_balance(balance_payload)
        position_details = self._normalise_positions_payload(positions_payload)

        return {
            "walletUSDT": wallet_balance,
            "positions": position_details,
            "balance": balance_payload,
            "positionsRaw": positions_payload,
        }

    async def get_open_positions(self, symbol: str | None = None) -> Any:
        """Return the currently open positions."""

        params: dict[str, Any] = {}
        if symbol:
            params["symbol"] = self._normalise_symbol(symbol)
        data = await self._request_with_fallback(
            "GET",
            self._swap_paths(
                PATH_USER_POSITIONS,
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

        try:
            payload = await self._request_with_fallback(
                "GET",
                self._swap_paths(
                    "quote/premiumIndex",
                    "quote/price",
                ),
                params=params,
                authenticated=False,
            )
        except BingXClientError as exc:
            if not self._is_missing_api_error(exc):
                raise
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

    async def get_symbol_filters(self, symbol: str) -> dict[str, Any]:
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

        payload = await self._request(
            "GET",
            PATH_QUOTE_CONTRACTS,
            authenticated=False,
        )

        contracts: list[Any] | None = None
        if isinstance(payload, list):
            contracts = payload
        elif isinstance(payload, Mapping):
            data = payload.get("data")
            if isinstance(data, list):
                contracts = data

        if contracts is None:
            raise BingXClientError(
                f"Unexpected contracts payload for {symbol!r}: {payload!r}"
            )

        contract: Mapping[str, Any] | None = None
        for candidate in contracts:
            if not isinstance(candidate, Mapping):
                continue
            candidate_symbol = candidate.get("symbol") or candidate.get("symbolName")
            if candidate_symbol == normalised_symbol:
                contract = candidate
                break

        if contract is None:
            raise BingXClientError(
                f"Symbol {normalised_symbol!r} not present in contracts payload"
            )

        normalized_filters = normalize_contract_filters(contract)

        try:
            step_size = float(Decimal(normalized_filters["stepSize"]))
            min_qty = float(Decimal(normalized_filters["minQty"]))
            tick_size = float(Decimal(normalized_filters["tickSize"]))
        except (KeyError, ArithmeticError, ValueError) as exc:
            raise BingXClientError(
                f"Quantity filters missing for {symbol!r}: {contract!r}"
            ) from exc

        min_notional = self._extract_float(
            contract,
            "minNotional",
            "min_notional",
            "notional",
            "minTradeAmount",
        )

        if min_qty is None or step_size is None:
            raise BingXClientError(
                f"Quantity filters missing for {symbol!r}: {contract!r}"
            )

        result: dict[str, float | int | dict[str, Any]] = {
            "min_qty": min_qty,
            "step_size": step_size,
            "tick_size": tick_size,
        }
        if min_notional is not None:
            result["min_notional"] = min_notional

        price_precision = normalized_filters.get("pricePrecision")
        if price_precision is not None:
            result["price_precision"] = price_precision

        quantity_precision = normalized_filters.get("quantityPrecision")
        if quantity_precision is not None:
            result["quantity_precision"] = quantity_precision

        result["raw_filters"] = normalized_filters

        if self.symbol_filters_ttl > 0:
            self._filters_cache[normalised_symbol] = (now, dict(result))

        return result

    def clear_symbol_filters_cache(self, symbol: str | None = None) -> None:
        """Invalidate cached symbol filter data."""

        if symbol is None:
            self._filters_cache.clear()
            return

        self._filters_cache.pop(self._normalise_symbol(symbol), None)

    # ------------------------------------------------------------------
    # Simplified REST helpers for Futures-only workflows
    # ------------------------------------------------------------------
    def sign_params(self, params: Mapping[str, Any] | None) -> str:
        """Return the canonical signature for *params* using the API secret."""

        return self._sign_parameters(params)

    async def post(self, path: str, params: Mapping[str, Any]) -> Any:
        """Send a POST request to the raw ``path`` using BingX authentication."""

        return await self._request("POST", path, params=params)

    async def set_margin_mode(
        self, symbol: str, marginMode: str, marginCoin: str | None = None
    ) -> Any:
        """Set the isolated/cross margin mode for *symbol*."""

        token = marginMode.strip().lower()
        if token not in {"isolated", "cross", "crossed"}:
            raise BingXClientError(
                "Ungültiger Margin-Modus. Erlaubt sind 'isolated' oder 'cross'."
            )

        canonical_mode = "ISOLATED" if token.startswith("isol") else "CROSSED"
        return await self.set_margin_type(
            symbol=symbol,
            margin_mode=canonical_mode,
            margin_coin=marginCoin,
        )

    async def place_market(
        self,
        symbol: str,
        side: str,
        qty: str,
        positionSide: str,
        *,
        reduceOnly: bool = False,
        closePosition: bool = False,
        clientOrderId: str = "",
    ) -> Any:
        """Place a MARKET order following the simplified Futures contract API."""

        params: MutableMapping[str, Any] = {
            "symbol": self._normalise_symbol(symbol),
            "side": side.strip().upper(),
            "type": "MARKET",
            "quantity": qty,
        }

        position_token = positionSide.strip().upper() if positionSide else ""
        if position_token and position_token != "BOTH":
            params["positionSide"] = position_token
        if reduceOnly:
            params["reduceOnly"] = "true"
        if closePosition:
            params["closePosition"] = "true"
        if clientOrderId:
            params["clientOrderId"] = clientOrderId

        assert_order_path(PATH_ORDER)
        return await self._request("POST", PATH_ORDER, params=params)

    async def place_limit(
        self,
        symbol: str,
        side: str,
        qty: str,
        price: str,
        tif: str,
        positionSide: str,
        *,
        reduceOnly: bool = False,
        closePosition: bool = False,
        clientOrderId: str = "",
    ) -> Any:
        """Place a LIMIT order with the specified time-in-force policy."""

        params: MutableMapping[str, Any] = {
            "symbol": self._normalise_symbol(symbol),
            "side": side.strip().upper(),
            "type": "LIMIT",
            "quantity": qty,
            "price": price,
            "timeInForce": tif.strip().upper(),
        }

        position_token = positionSide.strip().upper() if positionSide else ""
        if position_token and position_token != "BOTH":
            params["positionSide"] = position_token
        if reduceOnly:
            params["reduceOnly"] = "true"
        if closePosition:
            params["closePosition"] = "true"
        if clientOrderId:
            params["clientOrderId"] = clientOrderId

        assert_order_path(PATH_ORDER)
        return await self._request("POST", PATH_ORDER, params=params)

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
        close_position: bool | None = None,
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
        if close_position:
            params["closePosition"] = "true"
        if client_order_id is not None:
            params["clientOrderId"] = client_order_id

        assert_order_path(PATH_ORDER)
        return await self._request("POST", PATH_ORDER, params=params)

    async def place_futures_market_order(
        self,
        *,
        symbol: str,
        side: str,
        qty: float,
        reduce_only: bool = False,
        close_position: bool = False,
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
        if close_position:
            params["closePosition"] = "true"
        if client_order_id:
            params["clientOrderId"] = client_order_id

        LOGGER.info("Placing futures market order: %s", params)

        assert_order_path(PATH_ORDER)
        return await self._request("POST", PATH_ORDER, params=params)

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

        return await self._request("POST", PATH_SET_MARGIN, params=params)

    async def set_leverage(
        self,
        symbol: str,
        leverage: float | None = None,
        positionSide: str | None = None,
        *,
        lev_long: int | float | None = None,
        lev_short: int | float | None = None,
        hedge: bool | None = None,
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

        position_side_value = positionSide if positionSide is not None else position_side

        simple_call = (
            leverage is not None
            and lev_long is None
            and lev_short is None
            and leverage_long is None
            and leverage_short is None
        )

        if simple_call:
            pos_token = (position_side_value or "BOTH").strip().upper()
            side_token = side.strip().upper() if isinstance(side, str) else None

            if pos_token == "LONG":
                side_token = side_token or "BUY"
            elif pos_token == "SHORT":
                side_token = side_token or "SELL"
            elif pos_token == "BOTH":
                pos_token = None

            if isolated is not None and margin_mode is None:
                margin_mode = "ISOLATED" if isolated else "CROSSED"

            mode_token = margin_mode.strip().upper() if isinstance(margin_mode, str) else None
            if mode_token == "CROSS":
                mode_token = "CROSSED"

            return await self._set_single_leverage(
                symbol=symbol,
                leverage=leverage,
                margin_mode=mode_token,
                margin_coin=margin_coin,
                side=side_token,
                position_side=pos_token,
            )

        if leverage is not None and lev_long is None and lev_short is None:
            lev_long = lev_short = leverage

        if leverage_long is not None or leverage_short is not None:
            lev_long = leverage_long if leverage_long is not None else lev_long
            lev_short = leverage_short if leverage_short is not None else lev_short

        if lev_long is None and lev_short is None:
            raise ValueError(
                "Either a single leverage or both 'lev_long' and 'lev_short' must be provided."
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
            position_side=position_side_value,
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

        return await self._request("POST", PATH_SET_LEVERAGE, params=params)

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
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        authenticated: bool = True,
    ) -> Any:
        if not self._client:
            raise BingXClientError(
                "HTTP client not initialised. Use 'async with BingXClient(...)' when calling the API."
            )

        method_token = method.upper()
        if authenticated:
            query_string = self._sign_parameters(params)
        else:
            query_string = self._encode_parameters(
                params,
                include_timestamp=False,
                include_recv_window=False,
            )
        safe_payload = {
            key: value
            for key, value in (params or {}).items()
            if key != "signature"
        }

        def _redact_signature(text: str) -> str:
            if not text:
                return ""
            return re.sub(r"(signature=)[0-9a-fA-F]+", r"\1<redacted>", text)

        attempt = 0
        while True:
            headers: dict[str, str] = {}
            if authenticated:
                headers["X-BX-APIKEY"] = self.api_key

            request_kwargs: dict[str, Any] = {}
            if headers:
                request_kwargs["headers"] = headers
            canonical_url = path if path.startswith("http") else f"{self.base_url}{path}"
            url = path

            if method_token == "GET":
                if query_string:
                    url = f"{path}?{query_string}"
                full_url = canonical_url if url == path else f"{canonical_url}?{query_string}"
                LOGGER.info("→ %s %s", method_token, full_url)
                if query_string:
                    LOGGER.info("→ QUERY: %s", _redact_signature(query_string))
                LOGGER.debug(
                    "BingX request %s %s params=%s",
                    method_token,
                    full_url,
                    safe_payload,
                )
            else:
                headers["Content-Type"] = "application/x-www-form-urlencoded"
                request_kwargs["content"] = query_string.encode("utf-8") if query_string else b""
                LOGGER.info("→ %s %s", method_token, canonical_url)
                LOGGER.info("→ BODY: %s", _redact_signature(query_string))
                LOGGER.debug(
                    "BingX request %s %s body=%s",
                    method_token,
                    canonical_url,
                    safe_payload,
                )

            try:
                response = await self._client.request(method_token, url, **request_kwargs)
            except Exception as exc:  # pragma: no cover - httpx specific errors
                raise BingXClientError(f"HTTP request to BingX failed: {exc}") from exc

            status_code = response.status_code

            try:
                payload = response.json()
            except ValueError as exc:  # pragma: no cover - defensive programming
                raise BingXClientError("Failed to decode BingX response as JSON") from exc

            LOGGER.info(
                "BingX response %s %s status=%s payload=%s",
                method_token,
                canonical_url,
                status_code,
                payload,
            )

            if status_code == 429:
                if attempt >= self.max_retries:
                    raise BingXClientError("BingX rate limit exceeded")
                delay = min(2 ** attempt, 8) + random.random()
                LOGGER.warning("BingX rate limit hit (HTTP 429). Retrying in %.2fs", delay)
                await asyncio.sleep(delay)
                attempt += 1
                continue

            if status_code != 200:
                if isinstance(payload, Mapping):
                    error_payload: Mapping[str, Any] | dict[str, Any]
                    error_payload = {
                        "code": payload.get("code", f"HTTP {status_code}"),
                        "msg": payload.get("msg")
                        or payload.get("message")
                        or str(payload),
                    }
                else:
                    error_payload = {"code": f"HTTP {status_code}", "msg": str(payload)}

                raise BingXClientError(
                    format_bingx_error(
                        method_token,
                        canonical_url,
                        error_payload,
                        request_path=path,
                    )
                )

            if isinstance(payload, Mapping):
                code = payload.get("code")
                if code in (0, "0", None):
                    return payload.get("data", payload)

                message = payload.get("msg") or payload.get("message") or "Unknown error"
                message_lower = str(message).lower()

                if str(code) == "100400":
                    raise BingXClientError(
                        format_bingx_error(
                            method_token,
                            canonical_url,
                            {"code": code, "msg": message},
                            request_path=path,
                        )
                    )

                if "duplicate" in message_lower and "client" in message_lower:
                    LOGGER.info("Duplicate clientOrderId detected – treating as success")
                    return payload.get("data", payload)

                hint = _ERROR_HINTS.get(str(code))
                if hint is None:
                    if "signature" in message_lower or "timestamp" in message_lower:
                        hint = "Signatur-/Timestamp-Fehler – Uhrzeit & Sortierung prüfen."
                    elif any(token in message_lower for token in _RATE_LIMIT_TOKENS):
                        if attempt < self.max_retries:
                            delay = min(2 ** attempt, 8) + random.random()
                            LOGGER.warning(
                                "BingX rate limit response (code %s). Retrying in %.2fs", code, delay
                            )
                            await asyncio.sleep(delay)
                            attempt += 1
                            continue
                        hint = "Rate-Limit überschritten."

                if hint:
                    message = f"{message} ({hint})"

                raise BingXClientError(
                    format_bingx_error(
                        method_token,
                        canonical_url,
                        {"code": code, "msg": message},
                        request_path=path,
                    )
                )

            return payload

    async def _request_with_fallback(
        self,
        method: str,
        paths: tuple[str, ...],
        *,
        params: Mapping[str, Any] | None = None,
        authenticated: bool = True,
    ) -> Any:
        """Attempt the request using multiple API paths to support BingX upgrades."""

        if not paths:
            raise BingXClientError("No API paths provided for request")

        for path in paths:
            if "getmargin" in path.lower():
                LOGGER.error(
                    "getMargin endpoint is deprecated/invalid – do not use (%s)", path
                )
                raise BingXClientError(
                    "The BingX getMargin endpoint is deprecated and must not be used."
                )

        last_error: BingXClientError | None = None

        for path in paths:
            LOGGER.debug("Attempting BingX request %s %s", method, path)
            try:
                payload = await self._request(
                    method,
                    path,
                    params=params,
                    authenticated=authenticated,
                )
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
            canonical = BingXClient._swap_v2_path(endpoint)
            paths.append(canonical)
            swapped = canonical.replace("/swap/v2/", "/v2/swap/")
            paths.append(swapped)

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
    def _extract_wallet_balance(payload: Any) -> Any | None:
        """Extract the most relevant wallet balance from a balance payload."""

        def _iter_containers(value: Any) -> list[Mapping[str, Any]]:
            containers: list[Mapping[str, Any]] = []
            if isinstance(value, Mapping):
                containers.append(value)
                nested = value.get("data")
                if isinstance(nested, Mapping):
                    containers.extend(_iter_containers(nested))
                elif isinstance(nested, list):
                    for item in nested:
                        containers.extend(_iter_containers(item))
            elif isinstance(value, list):
                for item in value:
                    containers.extend(_iter_containers(item))
            return containers

        candidates: list[Any] = []
        for container in _iter_containers(payload):
            for key in (
                "walletBalance",
                "availableBalance",
                "availableMargin",
                "marginBalance",
                "equity",
                "balance",
                "USDT",
                "usdt",
            ):
                if key not in container:
                    continue
                value = container.get(key)
                if isinstance(value, Mapping):
                    for nested_key in (
                        "walletBalance",
                        "availableBalance",
                        "availableMargin",
                        "marginBalance",
                        "equity",
                        "balance",
                    ):
                        nested = value.get(nested_key)
                        if nested not in (None, ""):
                            candidates.append(nested)
                elif value not in (None, ""):
                    candidates.append(value)

        if not candidates:
            return None

        return candidates[0]

    @staticmethod
    def _normalise_positions_payload(payload: Any) -> list[dict[str, Any]]:
        """Normalise the raw positions payload to a simplified structure."""

        entries: list[Mapping[str, Any]] = []
        if isinstance(payload, Mapping):
            data = payload.get("data")
            if isinstance(data, list):
                entries.extend(item for item in data if isinstance(item, Mapping))
            elif isinstance(data, Mapping):
                entries.append(data)
            elif "symbol" in payload:
                entries.append(payload)
        elif isinstance(payload, list):
            entries.extend(item for item in payload if isinstance(item, Mapping))

        normalised: list[dict[str, Any]] = []
        for entry in entries:
            symbol = (
                entry.get("symbol")
                or entry.get("pair")
                or entry.get("contract")
                or entry.get("tradingPair")
            )
            side = entry.get("positionSide") or entry.get("side") or entry.get("direction")
            amount = (
                entry.get("positionAmt")
                or entry.get("positionSize")
                or entry.get("size")
                or entry.get("quantity")
            )
            entry_price = (
                entry.get("entryPrice")
                or entry.get("avgEntryPrice")
                or entry.get("avgPrice")
                or entry.get("price")
            )
            leverage = entry.get("leverage")
            margin_mode = entry.get("marginMode") or entry.get("marginType")
            if isinstance(margin_mode, str):
                margin_mode = margin_mode.lower()

            if margin_mode is None:
                isolated_flag = BingXClient._coerce_bool(entry.get("isolated"))
                if isolated_flag is True:
                    margin_mode = "isolated"
                elif isolated_flag is False:
                    margin_mode = "cross"

            position_margin = (
                entry.get("positionMargin")
                or entry.get("isolatedMargin")
                or entry.get("margin")
                or entry.get("maintMargin")
            )

            normalised.append(
                {
                    "symbol": symbol,
                    "positionSide": str(side).upper() if side is not None else None,
                    "positionAmt": amount,
                    "entryPrice": entry_price,
                    "leverage": leverage,
                    "marginMode": margin_mode,
                    "positionMargin": position_margin,
                }
            )

        return normalised

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

    def _encode_parameters(
        self,
        params: Mapping[str, Any] | None,
        *,
        include_timestamp: bool,
        include_recv_window: bool,
    ) -> str:
        """Return the canonical query string for *params* without signing."""

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

        if include_timestamp and "timestamp" not in payload:
            payload["timestamp"] = _stringify(int(time.time() * 1000))

        if include_recv_window and "recvWindow" not in payload and self.recv_window:
            payload["recvWindow"] = _stringify(self.recv_window)

        if not payload:
            return ""

        sorted_items = sorted(payload.items())

        return urlencode(
            sorted_items,
            safe="-_.~",
            quote_via=quote,
        )

    def _sign_parameters(self, params: Mapping[str, Any] | None) -> str:
        """Return the canonical query string with an attached HMAC signature."""

        canonical_query = self._encode_parameters(
            params,
            include_timestamp=True,
            include_recv_window=True,
        )

        signature = hmac.new(
            self.api_secret.encode("utf-8"),
            canonical_query.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        if canonical_query:
            return f"{canonical_query}&signature={signature}"
        return f"signature={signature}"


__all__ = ["BingXClient", "BingXClientError"]
