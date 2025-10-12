"""Helpers for applying BingX leverage settings consistently."""
from __future__ import annotations

import hashlib
import hmac
import os
import time
from typing import Any, Dict, Optional

import httpx

API_KEY = os.getenv("BINGX_KEY") or os.getenv("BINGX_API_KEY") or ""
API_SECRET = os.getenv("BINGX_SECRET") or os.getenv("BINGX_API_SECRET") or ""
BASE_URL = os.getenv("BINGX_BASE_URL") or "https://open-api.bingx.com"
RECV_WINDOW = int(os.getenv("BINGX_RECV_WINDOW", "5000") or "5000")


def _sign(params: Dict[str, Any]) -> str:
    query = "&".join(f"{key}={value}" for key, value in sorted(params.items()))
    signature = hmac.new(API_SECRET.encode(), query.encode(), hashlib.sha256).hexdigest()
    return f"{query}&signature={signature}"


async def _post_form(path: str, params: Dict[str, Any]) -> Dict[str, Any]:
    if not API_KEY or not API_SECRET:
        raise RuntimeError("BingX credentials are not configured")

    payload = {
        **params,
        "recvWindow": str(RECV_WINDOW),
        "timestamp": str(int(time.time() * 1000)),
    }
    body = _sign(payload)
    headers = {
        "X-BX-APIKEY": API_KEY,
        "Content-Type": "application/x-www-form-urlencoded",
    }

    async with httpx.AsyncClient(base_url=BASE_URL, timeout=10.0) as client:
        print("→ POST", f"{BASE_URL}{path}")
        redacted_body = body
        if API_SECRET:
            redacted_body = body.replace(API_SECRET, "<redacted>")
        print("→ BODY:", redacted_body)
        response = await client.post(path, content=body, headers=headers)
        print("HTTP", response.status_code, response.text)
        response.raise_for_status()
        return response.json()


def _clamp_leverage(sym_filters: Optional[Dict[str, Any]], leverage: int) -> int:
    max_lev: Optional[int] = None
    if sym_filters:
        candidate = (
            sym_filters.get("maxLeverage")
            or sym_filters.get("maxOpenLeverage")
            or sym_filters.get("maxPositionLeverage")
            or sym_filters.get("max_leverage")
        )
        try:
            if candidate is not None:
                max_lev = int(candidate)
        except (TypeError, ValueError):
            max_lev = None
    leverage = int(leverage)
    if leverage < 1:
        leverage = 1
    if max_lev:
        leverage = min(leverage, max_lev)
    else:
        leverage = min(leverage, 125)
    return leverage


async def set_leverage_for_side(symbol: str, leverage: int, position_side: str) -> Dict[str, Any]:
    side = position_side.upper()
    if side not in {"LONG", "SHORT"}:
        raise ValueError("positionSide muss LONG oder SHORT sein")

    params = {
        "symbol": symbol,
        "leverage": str(int(leverage)),
        "positionSide": side,
    }
    response = await _post_form("/openApi/swap/v2/trade/setLeverage", params)
    code = response.get("code")
    if code not in (0, "0"):
        raise RuntimeError(f"setLeverage({symbol},{side}) failed: {response}")
    return response


async def ensure_leverage_both(
    symbol: str,
    leverage: int,
    sym_filters: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Ensure the leverage is applied for LONG and SHORT sides in hedge mode."""

    effective_leverage = _clamp_leverage(sym_filters, leverage)
    long_response = await set_leverage_for_side(symbol, effective_leverage, "LONG")
    short_response = await set_leverage_for_side(symbol, effective_leverage, "SHORT")
    return {
        "leverage": effective_leverage,
        "LONG": long_response,
        "SHORT": short_response,
    }
