"""Minimal BingX REST client for order placement."""
from __future__ import annotations

import hashlib
import hmac
import logging
import time
from typing import Any, Dict, Iterable, Optional

import httpx

from tvtelegrambingx.config import Settings

LOGGER = logging.getLogger(__name__)

SETTINGS: Optional[Settings] = None


def _is_success_code(value: Any) -> bool:
    """Return ``True`` when the BingX response code indicates success."""

    if value in (None, 0, "0"):
        return True
    if isinstance(value, str):
        try:
            return int(value) == 0
        except ValueError:
            return False
    return False


def configure(settings: Settings) -> None:
    """Store settings for subsequent API calls."""
    global SETTINGS
    SETTINGS = settings


def _require_settings() -> Settings:
    if SETTINGS is None:
        raise RuntimeError("BingX client not configured")
    return SETTINGS


def _sign(secret: str, params: Dict[str, Any]) -> str:
    query = "&".join(f"{key}={value}" for key, value in sorted(params.items()))
    signature = hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()
    return f"{query}&signature={signature}"


def _format_quantity(value: float) -> str:
    """Return a string representation accepted by BingX."""

    return ("{0:.8f}".format(value)).rstrip("0").rstrip(".") or "0"


def _normalise_symbol(symbol: str) -> str:
    """Return a normalised symbol representation for comparison."""

    return symbol.replace("-", "").upper()


def _format_symbol_for_api(symbol: str) -> str:
    """Return a symbol representation preferred by the BingX API."""

    cleaned = _normalise_symbol(symbol)
    suffixes = (
        "USDT",
        "USDC",
        "BUSD",
        "FDUSD",
        "BIDR",
        "EUR",
        "USD",
        "BTC",
        "ETH",
    )
    for suffix in suffixes:
        if cleaned.endswith(suffix) and len(cleaned) > len(suffix):
            return f"{cleaned[:-len(suffix)]}-{suffix}"
    return cleaned


def _iter_symbol_variants(symbol: str) -> Iterable[str]:
    """Yield possible symbol representations accepted by BingX."""

    seen = set()
    for candidate in (
        symbol,
        symbol.upper(),
        _normalise_symbol(symbol),
        _format_symbol_for_api(symbol),
    ):
        candidate = candidate.strip() if isinstance(candidate, str) else symbol
        if candidate and candidate not in seen:
            seen.add(candidate)
            yield candidate


def _extract_price_from_payload(symbol: str, payload: Dict[str, Any]) -> Optional[float]:
    """Return the price contained in a BingX response payload, if available."""

    if not isinstance(payload, dict):
        return None

    data = payload.get("data")

    if isinstance(data, dict) and "list" in data and isinstance(data["list"], list):
        # Some responses wrap the actual data inside a "list" key.
        data = data["list"]

    if isinstance(data, list):
        selected: Optional[Dict[str, Any]] = None
        target_symbol = _normalise_symbol(symbol)
        for entry in data:
            if not isinstance(entry, dict):
                continue
            entry_symbol = _normalise_symbol(str(entry.get("symbol") or ""))
            if entry_symbol == target_symbol:
                selected = entry
                break
            if selected is None and any(
                entry.get(key) not in (None, "")
                for key in ("markPrice", "price", "indexPrice", "lastPrice", "close")
            ):
                selected = entry
        data = selected

    price_source: Dict[str, Any] = data if isinstance(data, dict) else {}
    possible_keys = (
        "markPrice",
        "price",
        "indexPrice",
        "lastPrice",
        "close",
        "marketPrice",
        "fairPrice",
        "avgPrice",
    )

    for key in possible_keys:
        raw_value = price_source.get(key)
        if raw_value in (None, ""):
            continue
        try:
            return float(raw_value)
        except (TypeError, ValueError):
            continue

    if isinstance(data, (int, float)):
        return float(data)

    if isinstance(data, str):
        try:
            return float(data)
        except ValueError:
            return None

    return None


async def get_latest_price(symbol: str) -> float:
    """Return the current mark price for a contract."""

    settings = _require_settings()
    endpoints = (
        "/openApi/swap/v2/quote/premiumIndex",
        "/openApi/swap/v2/quote/price",
        "/openApi/swap/v1/ticker/price",
    )

    async with httpx.AsyncClient(base_url=settings.bingx_base_url, timeout=10.0) as client:
        payloads = []
        for path in endpoints:
            for candidate in _iter_symbol_variants(symbol):
                response = await client.get(path, params={"symbol": candidate})
                response.raise_for_status()
                payload = response.json()
                price_value = _extract_price_from_payload(symbol, payload)
                if price_value is not None:
                    return price_value
                payloads.append((path, candidate, payload))

    for path, candidate, payload in payloads:
        LOGGER.debug(
            "Ungültige Preisantwort für %s (versucht mit %s) von %s: %s",
            symbol,
            candidate,
            path,
            payload,
        )

    raise RuntimeError(f"Konnte Markpreis für {symbol} nicht laden")


async def get_contract_filters(symbol: str) -> Dict[str, float]:
    """Return quantity and notional limits for the provided symbol."""

    settings = _require_settings()

    def _from_precision(value: Any) -> Optional[float]:
        try:
            precision = int(value)
        except (TypeError, ValueError):
            return None
        if precision < 0:
            return None
        return 10.0 ** (-precision)

    def _parse_contract(entry: Dict[str, Any]) -> Optional[Dict[str, float]]:
        lot_step_raw = (
            entry.get("quantityPrecisionStep")
            or entry.get("lotSize")
            or entry.get("stepSize")
            or _from_precision(entry.get("quantityPrecision"))
        )
        min_qty_raw = entry.get("minQty") or entry.get("minQuantity")
        min_notional_raw = entry.get("minNotional") or entry.get("minNotionalValue")

        try:
            lot_step = float(lot_step_raw) if lot_step_raw is not None else None
        except (TypeError, ValueError):
            lot_step = None

        if lot_step is None:
            lot_step = _from_precision(entry.get("quantityPrecision"))

        try:
            min_qty = float(min_qty_raw) if min_qty_raw is not None else None
        except (TypeError, ValueError):
            min_qty = None

        try:
            min_notional = float(min_notional_raw) if min_notional_raw is not None else None
        except (TypeError, ValueError):
            min_notional = None

        if lot_step is None or lot_step <= 0:
            lot_step = 0.001

        if min_qty is None or min_qty <= 0:
            min_qty = lot_step

        if min_notional is None or min_notional < 0:
            min_notional = 5.0

        return {
            "lot_step": float(lot_step),
            "min_qty": float(min_qty),
            "min_notional": float(min_notional),
        }

    async def _fetch_contracts(client: httpx.AsyncClient, candidate: str) -> Optional[Dict[str, float]]:
        response = await client.get("/openApi/swap/v2/quote/contracts", params={"symbol": candidate})
        if response.status_code != 200:
            return None
        payload = response.json()
        data = payload.get("data") if isinstance(payload, dict) else None
        items: Iterable[Any]
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            items = [data]
        else:
            items = []

        target_symbol = _normalise_symbol(candidate)
        for entry in items:
            if not isinstance(entry, dict):
                continue
            entry_symbol = _normalise_symbol(str(entry.get("symbol") or ""))
            if entry_symbol and entry_symbol != target_symbol:
                continue
            parsed = _parse_contract(entry)
            if parsed:
                return parsed
        return None

    async def _fetch_single_contract(client: httpx.AsyncClient, candidate: str) -> Optional[Dict[str, float]]:
        response = await client.get(
            "/openApi/swap/v2/market/getContract",
            params={"symbol": candidate},
        )
        if response.status_code != 200:
            return None
        payload = response.json()
        entry = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(entry, dict):
            return None
        return _parse_contract(entry)

    candidates = list(_iter_symbol_variants(symbol))
    if not symbol.endswith(".P"):
        candidates.append(f"{symbol}.P")
    else:
        candidates.append(symbol[:-2])

    async with httpx.AsyncClient(base_url=settings.bingx_base_url, timeout=10.0) as client:
        for candidate in candidates:
            result = await _fetch_contracts(client, candidate)
            if result:
                return result
        for candidate in candidates:
            result = await _fetch_single_contract(client, candidate)
            if result:
                return result

    LOGGER.warning("Falling back to default contract filters for %s", symbol)
    return {"lot_step": 0.001, "min_qty": 0.001, "min_notional": 5.0}


async def set_leverage(
    symbol: str,
    leverage: int,
    margin_mode: str = "ISOLATED",
    position_side: str = "BOTH",
) -> None:
    """Configure the leverage for the symbol when credentials are available."""
    settings = _require_settings()
    if leverage <= 0:
        raise RuntimeError("Hebel muss größer als 0 sein")

    if settings.dry_run or not settings.bingx_api_key or not settings.bingx_api_secret:
        LOGGER.info(
            "Skipping leverage update for %s due to dry-run or missing credentials",
            symbol,
        )
        return

    position_side = (position_side or "BOTH").upper()
    api_symbol = _format_symbol_for_api(symbol)

    def _build_payload(side_value: str) -> str:
        side_value = (side_value or "BOTH").upper()
        params = {
            "symbol": api_symbol,
            "leverage": int(leverage),
            "marginType": margin_mode,
            "marginMode": margin_mode,
            "positionSide": side_value,
            "side": side_value,
            "timestamp": int(time.time() * 1000),
            "recvWindow": settings.bingx_recv_window,
        }
        return _sign(settings.bingx_api_secret, params)

    headers = {
        "X-BX-APIKEY": settings.bingx_api_key,
        "Content-Type": "application/x-www-form-urlencoded",
    }

    async def _post_leverage(client: httpx.AsyncClient, payload: str) -> httpx.Response:
        response = await client.post(
            "/openApi/swap/v2/trade/leverage",
            content=payload,
            headers=headers,
        )
        LOGGER.info("BingX leverage response %s: %s", response.status_code, response.text)
        return response

    async with httpx.AsyncClient(base_url=settings.bingx_base_url, timeout=10.0) as client:
        response = await _post_leverage(client, _build_payload(position_side))
        if response.status_code != 200:
            raise RuntimeError("Fehler beim Setzen des Hebels")
        data = response.json()

        if isinstance(data, dict):
            code = data.get("code")
            message = data.get("msg") or data.get("message") or "Unbekannter Fehler"
            if _is_success_code(code):
                return

            requires_side = "side" in str(message).lower() or str(code) == "109414"
            if requires_side and position_side.upper() != "BOTH":
                retry_payload = _build_payload("BOTH")
                retry_response = await _post_leverage(client, retry_payload)
                LOGGER.info(
                    "BingX leverage retry response %s: %s",
                    retry_response.status_code,
                    retry_response.text,
                )
                if retry_response.status_code != 200:
                    raise RuntimeError("Fehler beim Setzen des Hebels (Retry)")
                retry_data = retry_response.json()
                if isinstance(retry_data, dict):
                    retry_code = retry_data.get("code")
                    if _is_success_code(retry_code):
                        return
                    retry_msg = (
                        retry_data.get("msg")
                        or retry_data.get("message")
                        or "Unbekannter Fehler"
                    )
                    raise RuntimeError(
                        f"BingX hat die Hebel-Einstellung abgelehnt: {retry_msg} (Code {retry_code})"
                    )
                raise RuntimeError("Ungültige Antwort beim Setzen des Hebels (Retry)")

            raise RuntimeError(
                f"BingX hat die Hebel-Einstellung abgelehnt: {message} (Code {code})"
            )

    raise RuntimeError("Ungültige Antwort beim Setzen des Hebels")


async def place_order(
    symbol: str,
    side: str,
    position_side: str,
    quantity: Optional[float] = None,
    reduce_only: bool = False,
) -> Dict[str, Any]:
    """Submit a market order to BingX.

    When `DRY_RUN` is enabled or the API credentials are missing, the payload is
    only logged. The quantity is taken from the signal when present, otherwise
    the configured default is used.
    """
    settings = _require_settings()

    order_quantity: Optional[float] = quantity
    if order_quantity is None:
        order_quantity = settings.bingx_default_quantity

    if order_quantity is None:
        raise RuntimeError("Keine Positionsgröße konfiguriert oder im Signal enthalten.")

    try:
        order_quantity = float(order_quantity)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("Ungültige Positionsgröße angegeben.") from exc

    if order_quantity <= 0:
        raise RuntimeError("Positionsgröße muss größer als 0 sein.")

    api_symbol = _format_symbol_for_api(symbol)

    params = {
        "symbol": api_symbol,
        "side": side,
        "positionSide": position_side,
        "type": "MARKET",
        "quantity": _format_quantity(order_quantity),
        "timestamp": int(time.time() * 1000),
        "recvWindow": settings.bingx_recv_window,
    }

    if reduce_only:
        params["reduceOnly"] = "true"

    if settings.dry_run or not settings.bingx_api_key or not settings.bingx_api_secret:
        LOGGER.info("Dry run enabled or missing credentials; skipping order: %s", params)
        return {"status": "skipped", "reason": "dry-run"}

    payload = _sign(settings.bingx_api_secret, params)
    headers = {
        "X-BX-APIKEY": settings.bingx_api_key,
        "Content-Type": "application/x-www-form-urlencoded",
    }

    async with httpx.AsyncClient(base_url=settings.bingx_base_url, timeout=10.0) as client:
        response = await client.post("/openApi/swap/v2/trade/order", content=payload, headers=headers)
        LOGGER.info("BingX response %s: %s", response.status_code, response.text)
        response.raise_for_status()

        try:
            data = response.json()
        except ValueError as exc:  # pragma: no cover - only triggered on invalid API responses
            LOGGER.exception("Failed to decode BingX response as JSON")
            raise RuntimeError("Ungültige Antwort von BingX erhalten") from exc

        if isinstance(data, dict):
            code = data.get("code")
            if not _is_success_code(code):
                message = data.get("msg") or data.get("message") or "Unbekannter Fehler"
                raise RuntimeError(f"BingX hat die Order abgelehnt: {message} (Code {code})")

        return data
