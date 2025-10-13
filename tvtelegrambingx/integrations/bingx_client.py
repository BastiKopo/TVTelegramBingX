from __future__ import annotations

import hashlib
import hmac
import logging
import os
import time
from urllib.parse import urlencode, quote
from typing import Any, Dict, Optional

import httpx

LOGGER = logging.getLogger(__name__)

_ENV_API_KEY = os.getenv("BINGX_KEY") or os.getenv("BINGX_API_KEY")
_ENV_API_SECRET = os.getenv("BINGX_SECRET") or os.getenv("BINGX_API_SECRET")
_ENV_BASE_URL = os.getenv("BINGX_BASE_URL") or "https://open-api.bingx.com"
_ENV_RECV_WINDOW = int(os.getenv("BINGX_RECV_WINDOW", "5000") or "5000")


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
        self.logger = LOGGER
        self._time_offset_ms = 0

    @property
    def _client(self) -> httpx.AsyncClient:
        if not hasattr(self, "__client") or getattr(self, "__client").is_closed:
            timeout = httpx.Timeout(15.0)
            self.__client = httpx.AsyncClient(timeout=timeout)
        return self.__client

    async def aclose(self) -> None:
        if hasattr(self, "__client") and not self.__client.is_closed:
            await self.__client.aclose()

    def _headers(self) -> Dict[str, str]:
        base = {"X-BX-APIKEY": self.api_key} if self.api_key else {}
        if base:
            base.setdefault("Content-Type", "application/x-www-form-urlencoded")
        return base

    async def _sync_time(self) -> None:
        """Synchronise the local clock with the BingX server time."""

        if not self.base_url:
            return

        try:
            response = await self._client.get(
                f"{self.base_url}/openApi/swap/v2/server/time",
                timeout=5.0,
            )
        except Exception:  # pragma: no cover - network failure
            self.logger.warning("Failed to sync time; continuing with local clock.")
            return

        if response.status_code != 200:
            return

        try:
            payload = response.json()
        except ValueError:  # pragma: no cover - malformed response
            return

        server_ts = (
            payload.get("serverTime")
            or payload.get("timestamp")
            or payload.get("data")
        )
        if server_ts is None:
            return

        try:
            server_ts_int = int(server_ts)
        except (TypeError, ValueError):
            return

        now = int(time.time() * 1000)
        self._time_offset_ms = server_ts_int - now
        self.logger.info("BingX time offset set to %d ms", self._time_offset_ms)

    def _now_ms(self) -> int:
        return int(time.time() * 1000) + int(self._time_offset_ms)

    def _canonical_qs(self, params: Dict[str, Any]) -> str:
        items = sorted(params.items(), key=lambda kv: kv[0])
        return urlencode(items, doseq=True, quote_via=quote, safe="")

    def _sign(self, params: Dict[str, Any]) -> Dict[str, Any]:
        if not self.api_key or not self.api_secret:
            raise RuntimeError("BingX credentials are not configured")

        params = params.copy()
        params.setdefault("timestamp", self._now_ms())
        params.setdefault("recvWindow", self.recv_window)

        params.pop("signature", None)
        params = {k: v for k, v in params.items() if v is not None}
        query = self._canonical_qs(params)
        signature = hmac.new(
            self.api_secret.encode("utf-8"),
            query.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        params["signature"] = signature
        return params

    async def _post_signed(self, path: str, params: Dict[str, Any], timeout: float = 10.0):
        signed = params if "signature" in params else self._sign(params)
        try:
            qs_no_sig = self._canonical_qs({k: v for k, v in signed.items() if k != "signature"})
            self.logger.debug("POST %s?%s&signature=<redacted>", path, qs_no_sig)
        except Exception:  # pragma: no cover - logging failure
            pass
        return await self._client.post(
            f"{self.base_url}{path}",
            params=signed,
            headers=self._headers(),
            timeout=timeout,
        )

    @staticmethod
    def normalize_symbol(symbol: str) -> str:
        if "-" in symbol:
            return symbol
        if symbol.upper().endswith("USDT"):
            return symbol[:-4] + "-USDT"
        return symbol

    async def _public_get(self, path: str, params: Dict[str, Any]) -> Dict[str, Any]:
        LOGGER.debug("BingX GET %s params=%s", path, params)
        response = await self._client.get(
            f"{self.base_url}{path}",
            params=params,
            headers=self._headers(),
            timeout=10.0,
        )
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

    async def get_contract(self, symbol: str) -> Dict[str, Any]:
        data = await self._public_get("/openApi/swap/v2/quote/contracts", {"symbol": symbol})
        contracts = data.get("data") if isinstance(data, dict) else None

        contract: Optional[Dict[str, Any]] = None
        if isinstance(contracts, dict):
            direct_contract = contracts.get(symbol)
            if isinstance(direct_contract, dict):
                contract = direct_contract
            else:
                fallback = contracts.get("contract")
                if isinstance(fallback, dict):
                    contract = fallback
                elif isinstance(contracts, dict):
                    contract = contracts
        if contract is None and isinstance(contracts, list):
            for entry in contracts:
                if isinstance(entry, dict) and entry.get("symbol") == symbol:
                    contract = entry
                    break

        if not isinstance(contract, dict):
            raise RuntimeError(f"Kontraktdaten für {symbol} nicht gefunden")

        return contract

    async def get_contract_filters(self, symbol: str) -> Dict[str, Any]:
        contract = await self.get_contract(symbol)

        lot_step_raw = (
            contract.get("stepSize")
            or contract.get("lotSize")
            or contract.get("lot_step")
            or "0.001"
        )
        min_qty_raw = contract.get("minQty") or contract.get("min_qty") or lot_step_raw
        min_notional_raw = (
            contract.get("minNotional")
            or contract.get("min_notional")
            or contract.get("minOrderValue")
            or "5.0"
        )

        try:
            lot_step = float(lot_step_raw)
        except (TypeError, ValueError):
            lot_step = 0.001
        try:
            min_qty = float(min_qty_raw)
        except (TypeError, ValueError):
            min_qty = lot_step
        try:
            min_notional = float(min_notional_raw)
        except (TypeError, ValueError):
            min_notional = 5.0

        return {
            "lot_step": lot_step,
            "min_qty": min_qty,
            "min_notional": min_notional,
            "raw_contract": contract,
        }

    async def set_leverage(
        self,
        symbol: str,
        leverage: int,
        margin_mode: str = "ISOLATED",
        position_side: str = "BOTH",
    ) -> Dict[str, Any]:
        """Set leverage with fallback handling for older endpoints."""

        log = getattr(self, "logger", logging.getLogger(__name__))
        norm_sym = self.normalize_symbol(symbol).upper()
        mode = (margin_mode or "ISOLATED").upper()

        def _build_params(side_val: str) -> Dict[str, Any]:
            side_name = (side_val or "BOTH").upper()
            base = {
                "timestamp": self._now_ms(),
                "symbol": norm_sym,
                "leverage": int(leverage),
                "marginType": mode,
                "positionSide": side_name,
                "side": side_name,
                "recvWindow": self.recv_window,
            }
            return base

        async def _call_v2(params: Dict[str, Any]):
            return await self._post_signed("/openApi/swap/v2/trade/leverage", params)

        async def _call_v1(params: Dict[str, Any]):
            return await self._post_signed("/openApi/swap/v1/trade/leverage", params)

        if self._time_offset_ms == 0:
            await self._sync_time()

        response = await _call_v2(_build_params(position_side))
        log.info("BingX leverage response %s: %s (path=v2)", response.status_code, response.text)
        if response.status_code != 200:
            raise RuntimeError("Fehler beim Setzen des Hebels")

        payload = response.json()
        code = str(payload.get("code", "0"))
        message = payload.get("msg", "")

        if code == "0":
            return payload

        if code == "100400" or "not exist" in message.lower():
            response_v1 = await _call_v1(_build_params(position_side))
            log.info(
                "BingX leverage v1 response %s: %s",
                response_v1.status_code,
                response_v1.text,
            )
            if response_v1.status_code != 200:
                raise RuntimeError("Fehler beim Setzen des Hebels (v1)")

            payload_v1 = response_v1.json()
            code_v1 = str(payload_v1.get("code", "0"))
            message_v1 = payload_v1.get("msg", "")
            if code_v1 == "0":
                return payload_v1
            message = message_v1
            code = code_v1

        if "side" in message.lower() or code == "109414":
            response_retry = await _call_v2(_build_params("BOTH"))
            log.info(
                "BingX leverage retry response %s: %s (path=v2)",
                response_retry.status_code,
                response_retry.text,
            )
            if response_retry.status_code == 200:
                retry_payload = response_retry.json()
                if str(retry_payload.get("code", "0")) == "0":
                    return retry_payload

            response_retry_v1 = await _call_v1(_build_params("BOTH"))
            log.info(
                "BingX leverage v1 retry response %s: %s",
                response_retry_v1.status_code,
                response_retry_v1.text,
            )
            if response_retry_v1.status_code == 200:
                retry_payload_v1 = response_retry_v1.json()
                if str(retry_payload_v1.get("code", "0")) == "0":
                    return retry_payload_v1

        raise RuntimeError(
            f"BingX hat die Hebel-Einstellung abgelehnt: {message} (Code {code})"
        )

    async def place_order(
        self,
        symbol: str,
        side: str,
        qty: float,
        reduce_only: bool = False,
        position_side: Optional[str] = None,
    ) -> Dict[str, Any]:
        quantity = float(qty)
        if quantity <= 0:
            raise RuntimeError("quantity muss > 0 sein")

        if self._time_offset_ms == 0:
            await self._sync_time()

        qty_str = ("%.12f" % quantity).rstrip("0").rstrip(".")

        order_side = side.upper()
        pos_side = position_side.upper() if position_side else None

        normalized_symbol = self.normalize_symbol(symbol).upper()

        params: Dict[str, Any] = {
            "timestamp": self._now_ms(),
            "symbol": normalized_symbol,
            "side": order_side,
            "type": "MARKET",
            "quantity": qty_str,
            "recvWindow": self.recv_window,
        }

        if pos_side:
            params["positionSide"] = pos_side
        else:
            params["reduceOnly"] = "true" if reduce_only else "false"

        signed = self._sign(params)
        self.logger.info(
            "→ BODY (order): %s",
            "&".join(
                f"{key}={signed[key]}"
                for key in sorted(signed)
                if key != "signature"
            ),
        )
        response = await self._post_signed(
            "/openApi/swap/v2/trade/order",
            signed,
            timeout=10.0,
        )
        response.raise_for_status()
        return response.json()


_CLIENT = BingXClient()


async def place_order(
    symbol: str,
    side: str,
    *,
    qty: float,
    reduce_only: bool = False,
    position_side: Optional[str] = None,
) -> Dict[str, Any]:
    return await _CLIENT.place_order(
        symbol=symbol,
        side=side,
        qty=qty,
        reduce_only=reduce_only,
        position_side=position_side,
    )


async def get_latest_price(symbol: str) -> float:
    return await _CLIENT.get_latest_price(symbol)


async def get_contract_filters(symbol: str) -> Dict[str, Any]:
    return await _CLIENT.get_contract_filters(symbol)


async def get_contract(symbol: str) -> Dict[str, Any]:
    return await _CLIENT.get_contract(symbol)


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
        position_side=position_side or "BOTH",
    )
