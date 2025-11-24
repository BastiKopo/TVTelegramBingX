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


def _is_success_code(value: Any) -> bool:
    if value in (None, 0, "0"):
        return True
    if isinstance(value, str):
        try:
            return int(value) == 0
        except ValueError:
            return False
    return False


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
        # Preferred signature mode. Automatically toggled if BingX responds with
        # code 100001 (signature mismatch). The available modes are:
        #
        # ``raw``          → plain key=value pairs in insertion order
        # ``url``          → URL encoded pairs in insertion order
        # ``raw-sorted``   → plain key=value pairs sorted by key
        # ``url-sorted``   → URL encoded pairs sorted by key
        self._sig_mode = "raw"
        # Preferred transport mode: "query" (params) or "form" (body data).
        self._tx_mode = "query"

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

    def _serialize_params(
        self,
        params: Dict[str, Any],
        *,
        encode: bool,
        sort: bool,
    ) -> str:
        """Serialize ``params`` respecting encoding and ordering preferences."""

        items: list[tuple[str, Any]]
        if sort:
            items = sorted(params.items(), key=lambda kv: kv[0])
        else:
            items = [(key, value) for key, value in params.items()]

        filtered = [(key, value) for key, value in items if value is not None]

        if encode:
            return urlencode(filtered, doseq=True, quote_via=quote, safe="")

        return "&".join(f"{key}={value}" for key, value in filtered)

    def _canonical_qs(self, params: Dict[str, Any], *, sort: bool = True) -> str:
        """Return a URL-encoded query string."""

        return self._serialize_params(params, encode=True, sort=sort)

    def _raw_qs(self, params: Dict[str, Any], *, sort: bool = True) -> str:
        """Return a raw (non-URL-encoded) query string."""

        return self._serialize_params(params, encode=False, sort=sort)

    def _sig_mode_flags(self, mode: Optional[str]) -> tuple[bool, bool]:
        """Return ``(encode, sort)`` flags for the signature mode."""

        current = (mode or self._sig_mode or "raw").lower()
        encode = "url" in current
        sort = "sorted" in current or "canonical" in current
        return encode, sort

    def _sign(self, params: Dict[str, Any], mode: Optional[str] = None) -> Dict[str, Any]:
        if not self.api_key or not self.api_secret:
            raise RuntimeError("BingX credentials are not configured")

        cleaned: Dict[str, Any] = params.copy()
        cleaned.setdefault("timestamp", self._now_ms())
        cleaned.setdefault("recvWindow", self.recv_window)

        cleaned.pop("signature", None)
        cleaned = {k: v for k, v in cleaned.items() if v is not None}

        encode, sort = self._sig_mode_flags(mode)
        if encode:
            payload = self._canonical_qs(cleaned, sort=sort)
        else:
            payload = self._raw_qs(cleaned, sort=sort)

        signature = hmac.new(
            self.api_secret.encode("utf-8"),
            payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        cleaned["signature"] = signature
        return cleaned

    async def _post_signed(self, path: str, params: Dict[str, Any], timeout: float = 10.0):
        """POST request with signature handling and automatic fallback."""

        using_external_signature = "signature" in params

        async def _do(sig_mode: str, tx_mode: str) -> httpx.Response:
            payload_params = dict(params)
            if not using_external_signature:
                payload_params["timestamp"] = self._now_ms()
                signed = self._sign(payload_params, sig_mode)
            else:
                signed = payload_params

            try:
                encode, sort = self._sig_mode_flags(sig_mode)
                qs_no_sig = self._serialize_params(
                    {k: v for k, v in signed.items() if k != "signature"},
                    encode=encode,
                    sort=sort,
                )
                suffix = "&signature=<redacted>"
                self.logger.debug(
                    "POST %s?%s%s (sig=%s tx=%s)",
                    path,
                    qs_no_sig,
                    suffix,
                    sig_mode,
                    tx_mode,
                )
            except Exception:  # pragma: no cover - logging failure
                pass

            url = f"{self.base_url}{path}"
            if tx_mode == "form":
                return await self._client.post(
                    url,
                    data=signed,
                    headers=self._headers(),
                    timeout=timeout,
                )
            return await self._client.post(
                url,
                params=signed,
                headers=self._headers(),
                timeout=timeout,
            )

        response = await _do(self._sig_mode, self._tx_mode)

        if using_external_signature:
            return response

        def _is_mismatch(resp: httpx.Response) -> bool:
            if resp.status_code != 200:
                return False
            try:
                payload = resp.json()
            except ValueError:
                return False
            return isinstance(payload, dict) and str(payload.get("code")) == "100001"

        if _is_mismatch(response):
            self.logger.warning(
                "Signature mismatch (sig=%s, tx=%s) → toggling signature mode",
                self._sig_mode,
                self._tx_mode,
            )

            sig_modes = ["raw", "url", "raw-sorted", "url-sorted"]
            try:
                current_index = sig_modes.index(self._sig_mode)
            except ValueError:
                current_index = -1
            alt_sig = sig_modes[(current_index + 1) % len(sig_modes)]
            retry_sig = await _do(alt_sig, self._tx_mode)
            if not _is_mismatch(retry_sig):
                if retry_sig.status_code == 200:
                    self.logger.info("Switching signature mode %s → %s", self._sig_mode, alt_sig)
                    self._sig_mode = alt_sig
                return retry_sig

            self.logger.warning(
                "Still mismatch after signature toggle → toggling transport mode",
            )
            alt_tx = "form" if self._tx_mode == "query" else "query"
            retry_both = await _do(alt_sig, alt_tx)
            if not _is_mismatch(retry_both):
                if retry_both.status_code == 200:
                    self.logger.info(
                        "Switching signature mode %s → %s and transport %s → %s",
                        self._sig_mode,
                        alt_sig,
                        self._tx_mode,
                        alt_tx,
                    )
                    self._sig_mode = alt_sig
                    self._tx_mode = alt_tx
                return retry_both

            retry_transport = await _do(self._sig_mode, alt_tx)
            if not _is_mismatch(retry_transport) and retry_transport.status_code == 200:
                self.logger.info(
                    "Switching transport %s → %s",
                    self._tx_mode,
                    alt_tx,
                )
                self._tx_mode = alt_tx
            return retry_transport

        return response

    async def _post_leverage_attempt(
        self,
        path: str,
        params: Dict[str, Any],
        label: str,
    ) -> httpx.Response:
        """Execute a single leverage attempt and log the request/response."""

        payload = dict(params)
        log_params = {
            key: payload[key]
            for key in sorted(payload)
            if key not in {"timestamp", "signature"}
        }
        self.logger.info("Leverage attempt %s path=%s params=%s", label, path, log_params)
        response = await self._post_signed(path, payload, timeout=10.0)
        self.logger.info(
            "Leverage attempt %s → http %s body=%s",
            label,
            response.status_code,
            response.text,
        )
        return response

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

        norm_sym_dash = self.normalize_symbol(symbol).upper()
        norm_sym_flat = norm_sym_dash.replace("-", "")
        mode = (margin_mode or "ISOLATED").upper()
        side = (position_side or "BOTH").upper()

        # Ensure the local timestamp is aligned with the BingX server clock.
        if self._time_offset_ms == 0:
            await self._sync_time()

        def _base(sym: str) -> Dict[str, Any]:
            return {
                "symbol": sym,
                "leverage": int(leverage),
                "recvWindow": self.recv_window,
            }

        profiles: list[tuple[str, Dict[str, Any]]] = [
            (
                "v2-A(dash,marginType,positionSide)",
                {**_base(norm_sym_dash), "marginType": mode, "positionSide": side},
            ),
            (
                "v2-B(dash,marginType,positionSide,side)",
                {
                    **_base(norm_sym_dash),
                    "marginType": mode,
                    "positionSide": side,
                    "side": side,
                },
            ),
            (
                "v2-C(dash,marginMode,positionSide)",
                {**_base(norm_sym_dash), "marginMode": mode, "positionSide": side},
            ),
            (
                "v2-D(dash,marginMode,positionSide,side)",
                {
                    **_base(norm_sym_dash),
                    "marginMode": mode,
                    "positionSide": side,
                    "side": side,
                },
            ),
            (
                "v2-E(flat,marginType,positionSide)",
                {**_base(norm_sym_flat), "marginType": mode, "positionSide": side},
            ),
            (
                "v1-A(flat,marginType,positionSide)",
                {
                    **_base(norm_sym_flat),
                    "marginType": mode,
                    "positionSide": side,
                    "_v": "v1",
                },
            ),
            (
                "v1-B(dash,marginType,positionSide)",
                {
                    **_base(norm_sym_dash),
                    "marginType": mode,
                    "positionSide": side,
                    "_v": "v1",
                },
            ),
        ]

        last_response: httpx.Response | None = None
        for label, params in profiles:
            params = dict(params)
            version = params.pop("_v", "v2")
            path = (
                "/openApi/swap/v1/trade/leverage"
                if version == "v1"
                else "/openApi/swap/v2/trade/leverage"
            )
            params["timestamp"] = self._now_ms()
            response = await self._post_leverage_attempt(path, params, label)
            last_response = response

            if response.status_code != 200:
                continue

            try:
                payload = response.json()
            except ValueError:
                continue

            code = str(payload.get("code", ""))
            if code == "0":
                return payload

            message = str(payload.get("msg", ""))
            if "not exist" in message.lower():
                continue

        msg = last_response.text if last_response is not None else "no response"
        raise RuntimeError(f"BingX hat die Hebel-Einstellung abgelehnt: {msg}")

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

        response = await self._post_signed(
            "/openApi/swap/v2/trade/order",
            params,
            timeout=10.0,
        )
        response.raise_for_status()
        payload = response.json()
        if not _is_success_code(payload.get("code")):
            msg = payload.get("msg") or payload
            raise RuntimeError(f"BingX Order abgelehnt: {msg}")

        return payload


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
