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


async def place_order(
    symbol: str,
    side: str,
    position_side: str,
    quantity: Optional[float] = None,
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
            if code not in (None, 0):
                message = data.get("msg") or data.get("message") or "Unbekannter Fehler"
                raise RuntimeError(f"BingX hat die Order abgelehnt: {message} (Code {code})")

        return data
