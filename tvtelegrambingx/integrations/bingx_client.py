from __future__ import annotations

import hashlib
import hmac
import logging
import os
import time
from typing import Any, Dict, Optional

import httpx

LOGGER = logging.getLogger(__name__)

_ENV_API_KEY = os.getenv("BINGX_KEY") or os.getenv("BINGX_API_KEY")
_ENV_API_SECRET = os.getenv("BINGX_SECRET") or os.getenv("BINGX_API_SECRET")
_ENV_BASE_URL = os.getenv("BINGX_BASE_URL") or "https://open-api.bingx.com"
_ENV_RECV_WINDOW = int(os.getenv("BINGX_RECV_WINDOW", "5000") or "5000")


def _format_quantity(value: float) -> str:
    return ("%.12f" % value).rstrip("0").rstrip(".")


def _sign(secret: str, params: Dict[str, Any]) -> str:
    query = "&".join(f"{key}={value}" for key, value in sorted(params.items()))
    signature = hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()
    return f"{query}&signature={signature}"


class BingXClient:
    """Small helper around the BingX REST API."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        base_url: str | None = None,
        recv_window: int | None = None,
    ) -> None:
        self.api_key = api_key or _ENV_API_KEY or ""
        self.api_secret = api_secret or _ENV_API_SECRET or ""
        self.base_url = base_url or _ENV_BASE_URL
        self.recv_window = recv_window or _ENV_RECV_WINDOW

    async def _signed_post(self, path: str, params: Dict[str, Any]) -> Dict[str, Any]:
        if not self.api_key or not self.api_secret:
            raise RuntimeError("BingX credentials are not configured")

        payload = {
            **params,
            "timestamp": int(time.time() * 1000),
            "recvWindow": self.recv_window,
        }
        body = _sign(self.api_secret, payload)
        headers = {
            "X-BX-APIKEY": self.api_key,
            "Content-Type": "application/x-www-form-urlencoded",
        }

        async with httpx.AsyncClient(base_url=self.base_url, timeout=15.0) as client:
            LOGGER.debug("BingX POST %s body=%s", path, body)
            response = await client.post(path, content=body, headers=headers)
            LOGGER.debug("BingX POST %s → %s %s", path, response.status_code, response.text)
            response.raise_for_status()
            return response.json()

    async def _public_get(self, path: str, params: Dict[str, Any]) -> Dict[str, Any]:
        async with httpx.AsyncClient(base_url=self.base_url, timeout=10.0) as client:
            LOGGER.debug("BingX GET %s params=%s", path, params)
            response = await client.get(path, params=params)
            LOGGER.debug("BingX GET %s → %s %s", path, response.status_code, response.text)
            response.raise_for_status()
            return response.json()

    async def get_latest_price(self, symbol: str) -> float:
        data = await self._public_get("/openApi/swap/v2/quote/price", {"symbol": symbol})
        price = (data.get("data") or {}).get("price") if isinstance(data, dict) else None
        try:
            return float(price)
        except (TypeError, ValueError) as exc:
            raise RuntimeError(f"Konnte Preis für {symbol} nicht laden") from exc

    async def get_contract_filters(self, symbol: str) -> Dict[str, Any]:
        data = await self._public_get("/openApi/swap/v2/quote/contracts", {"symbol": symbol})
        contracts = data.get("data") if isinstance(data, dict) else None
        if isinstance(contracts, dict):
            contract = contracts.get(symbol) or contracts.get("contract")
            if isinstance(contract, dict):
                contracts = contract
        if isinstance(contracts, list):
            for entry in contracts:
                if isinstance(entry, dict) and entry.get("symbol") == symbol:
                    contracts = entry
                    break

        lot_step = float((contracts or {}).get("lotSize") or (contracts or {}).get("lot_step") or 0.001)
        min_qty = float((contracts or {}).get("minQty") or (contracts or {}).get("min_qty") or lot_step)
        min_notional = float((contracts or {}).get("minNotional") or (contracts or {}).get("min_notional") or 5.0)

        return {
            "lot_step": lot_step,
            "min_qty": min_qty,
            "min_notional": min_notional,
        }

    async def set_leverage(
        self,
        symbol: str,
        leverage: int,
        margin_mode: str = "ISOLATED",
        position_side: Optional[str] = None,
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {
            "symbol": symbol,
            "leverage": leverage,
            "marginMode": margin_mode,
        }
        if position_side:
            params["positionSide"] = position_side
        return await self._signed_post("/openApi/swap/v2/trade/leverage", params)

    async def place_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        *,
        reduce_only: bool = False,
        position_side: Optional[str] = None,
    ) -> Dict[str, Any]:
        try:
            qty = float(quantity)
        except (TypeError, ValueError) as exc:
            raise RuntimeError("quantity ist ungültig/leer") from exc
        if qty <= 0:
            raise RuntimeError("quantity muss > 0 sein")

        params: Dict[str, Any] = {
            "symbol": symbol,
            "side": side,
            "type": "MARKET",
            "quantity": _format_quantity(qty),
        }
        if position_side:
            params["positionSide"] = position_side
        else:
            params["reduceOnly"] = "true" if reduce_only else "false"

        return await self._signed_post("/openApi/swap/v2/trade/order", params)


_CLIENT = BingXClient()


async def place_order(
    symbol: str,
    side: str,
    quantity: float,
    *,
    reduce_only: bool = False,
    position_side: Optional[str] = None,
) -> Dict[str, Any]:
    return await _CLIENT.place_order(
        symbol=symbol,
        side=side,
        quantity=quantity,
        reduce_only=reduce_only,
        position_side=position_side,
    )


async def get_latest_price(symbol: str) -> float:
    return await _CLIENT.get_latest_price(symbol)


async def get_contract_filters(symbol: str) -> Dict[str, Any]:
    return await _CLIENT.get_contract_filters(symbol)


async def set_leverage(
    symbol: str,
    leverage: int,
    margin_mode: str = "ISOLATED",
    position_side: Optional[str] = None,
) -> Dict[str, Any]:
    return await _CLIENT.set_leverage(
        symbol=symbol,
        leverage=leverage,
        margin_mode=margin_mode,
        position_side=position_side,
    )
