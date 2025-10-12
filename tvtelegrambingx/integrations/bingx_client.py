from __future__ import annotations

import hashlib
import hmac
import os
import time

import httpx

API_KEY = os.getenv("BINGX_KEY") or os.getenv("BINGX_API_KEY", "")
API_SECRET = os.getenv("BINGX_SECRET") or os.getenv("BINGX_API_SECRET", "")
BASE = os.getenv("BINGX_BASE_URL", "https://open-api.bingx.com")


def _sign(params: dict) -> str:
    query = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
    sig = hmac.new(API_SECRET.encode(), query.encode(), hashlib.sha256).hexdigest()
    return f"{query}&signature={sig}"


async def place_order(symbol: str, side: str, position_side: str):
    if not API_KEY or not API_SECRET:
        raise RuntimeError("BingX credentials are not configured")

    params = {
        "symbol": symbol,
        "side": side,
        "positionSide": position_side,
        "type": "MARKET",
        "timestamp": int(time.time() * 1000),
        "recvWindow": 5000,
    }
    body = _sign(params)
    url = f"{BASE}/openApi/swap/v2/trade/order"
    headers = {
        "X-BX-APIKEY": API_KEY,
        "Content-Type": "application/x-www-form-urlencoded",
    }
    async with httpx.AsyncClient(timeout=15) as client:
        print("→ POST", url)
        print("→ BODY:", body.replace(API_SECRET, "<redacted>"))
        response = await client.post(url, content=body, headers=headers)
        print("HTTP", response.status_code, response.text)
        response.raise_for_status()
        return response.json()
