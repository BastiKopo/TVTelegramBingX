"""Minimal BingX REST client for order placement."""
from __future__ import annotations

import hashlib
import hmac
import logging
import time
from typing import Any, Dict, Optional

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


async def get_latest_price(symbol: str) -> float:
    """Return the current mark price for a contract."""
    settings = _require_settings()
    async with httpx.AsyncClient(base_url=settings.bingx_base_url, timeout=10.0) as client:
        response = await client.get(
            "/openApi/swap/v2/quote/premiumIndex",
            params={"symbol": symbol},
        )
        response.raise_for_status()
        payload = response.json()

    data = payload.get("data") if isinstance(payload, dict) else None

    if isinstance(data, dict) and "list" in data and isinstance(data["list"], list):
        # Some responses wrap the actual data inside a "list" key
        data = data["list"]

    if isinstance(data, list):
        selected = None
        for entry in data:
            if not isinstance(entry, dict):
                continue
            if entry.get("symbol") == symbol:
                selected = entry
                break
            if selected is None and (entry.get("markPrice") or entry.get("price")):
                selected = entry
        data = selected

    price = (data or {}).get("markPrice") or (data or {}).get("price")
    try:
        return float(price)
    except (TypeError, ValueError) as exc:
        LOGGER.debug("Ungültige Preisantwort für %s: %s", symbol, payload)
        raise RuntimeError(f"Konnte Markpreis für {symbol} nicht laden") from exc


async def get_contract_filters(symbol: str) -> Dict[str, float]:
    """Return quantity and notional limits for the provided symbol."""
    settings = _require_settings()
    async with httpx.AsyncClient(base_url=settings.bingx_base_url, timeout=10.0) as client:
        response = await client.get(
            "/openApi/swap/v2/quote/contracts",
            params={"symbol": symbol},
        )
        response.raise_for_status()
        payload = response.json()

    data = payload.get("data") if isinstance(payload, dict) else None
    if isinstance(data, list):
        for entry in data:
            if isinstance(entry, dict) and entry.get("symbol") == symbol:
                data = entry
                break
        else:
            data = data[0] if data else None

    if not isinstance(data, dict):
        raise RuntimeError(f"Keine Handelsparameter für {symbol} erhalten")

    try:
        lot_step = float(data.get("lotSize") or data.get("stepSize") or 0)
        min_qty = float(data.get("minQty") or 0)
        min_notional = float(data.get("minNotional") or data.get("minNotionalValue") or 0)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"Ungültige Filterdaten für {symbol} erhalten") from exc

    if lot_step <= 0 or min_qty <= 0 or min_notional < 0:
        raise RuntimeError(f"Unvollständige Handelsparameter für {symbol} erhalten")

    return {
        "lot_step": lot_step,
        "min_qty": min_qty,
        "min_notional": max(min_notional, 0.0),
    }


async def set_leverage(symbol: str, leverage: int, margin_mode: str = "ISOLATED") -> None:
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

    params = {
        "symbol": symbol,
        "leverage": leverage,
        "marginType": margin_mode,
        "marginMode": margin_mode,
        "timestamp": int(time.time() * 1000),
        "recvWindow": settings.bingx_recv_window,
    }

    payload = _sign(settings.bingx_api_secret, params)
    headers = {
        "X-BX-APIKEY": settings.bingx_api_key,
        "Content-Type": "application/x-www-form-urlencoded",
    }

    async with httpx.AsyncClient(base_url=settings.bingx_base_url, timeout=10.0) as client:
        response = await client.post(
            "/openApi/swap/v2/trade/leverage",
            content=payload,
            headers=headers,
        )
        LOGGER.info("BingX leverage response %s: %s", response.status_code, response.text)
        response.raise_for_status()
        data = response.json()

    if isinstance(data, dict):
        code = data.get("code")
        if not _is_success_code(code):
            message = data.get("msg") or data.get("message") or "Unbekannter Fehler"
            raise RuntimeError(f"BingX hat die Hebel-Einstellung abgelehnt: {message} (Code {code})")


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

    params = {
        "symbol": symbol,
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
