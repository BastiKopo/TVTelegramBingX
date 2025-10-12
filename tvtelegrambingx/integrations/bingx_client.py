"""Async helper for placing BingX orders."""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import time
from typing import Any, Final

import httpx

LOGGER: Final = logging.getLogger(__name__)

_API_KEY_ENV: Final = "BINGX_KEY"
_API_SECRET_ENV: Final = "BINGX_SECRET"
_BASE_URL_ENV: Final = "BINGX_BASE_URL"
_DEFAULT_BASE_URL: Final = "https://open-api.bingx.com"

_ORDER_PATH: Final = "/openApi/swap/v2/trade/order"


def _get_credentials() -> tuple[str, str]:
    """Return the API key/secret pair from the environment."""

    api_key = os.getenv(_API_KEY_ENV)
    api_secret = os.getenv(_API_SECRET_ENV)
    if not api_key or not api_secret:
        raise RuntimeError(
            "Missing BingX credentials. Set BINGX_KEY and BINGX_SECRET environment variables."
        )
    return api_key, api_secret


def _sign_query(params: dict[str, Any], secret: str) -> str:
    """Return the signed query string for *params* using ``secret``."""

    canonical = "&".join(f"{key}={value}" for key, value in sorted(params.items()))
    signature = hmac.new(secret.encode(), canonical.encode(), hashlib.sha256).hexdigest()
    return f"{canonical}&signature={signature}"


async def place_order(symbol: str, side: str, position_side: str) -> dict[str, Any]:
    """Place a market order via the BingX REST API."""

    api_key, api_secret = _get_credentials()
    base_url = os.getenv(_BASE_URL_ENV, _DEFAULT_BASE_URL)

    params: dict[str, Any] = {
        "symbol": symbol,
        "side": side,
        "positionSide": position_side,
        "type": "MARKET",
        "timestamp": int(time.time() * 1000),
        "recvWindow": 5000,
    }

    query = _sign_query(params, api_secret)
    url = f"{base_url.rstrip('/')}{_ORDER_PATH}"
    headers = {
        "X-BX-APIKEY": api_key,
        "Content-Type": "application/x-www-form-urlencoded",
    }

    LOGGER.info("[BINGX] Sende Order: %s", query)

    async with httpx.AsyncClient() as client:
        response = await client.post(url, content=query, headers=headers, timeout=10.0)
        response.raise_for_status()
        LOGGER.info("[BINGX] Response %s: %s", response.status_code, response.text)
        return response.json()


__all__ = ["place_order"]
