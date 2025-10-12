"""Helpers for retrieving BingX account state."""
from __future__ import annotations

import hashlib
import hmac
import logging
import time
from typing import Any, Dict, List, Optional

import httpx

from tvtelegrambingx.config import Settings

LOGGER = logging.getLogger(__name__)

SETTINGS: Optional[Settings] = None


def configure(settings: Settings) -> None:
    """Store the shared settings for account requests."""
    global SETTINGS
    SETTINGS = settings


def _require_settings() -> Settings:
    if SETTINGS is None:
        raise RuntimeError("BingX account client not configured")
    return SETTINGS


def _sign(secret: str, params: Dict[str, Any]) -> str:
    query = "&".join(f"{key}={value}" for key, value in sorted(params.items()))
    signature = hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()
    return f"{query}&signature={signature}"


async def _signed_get(path: str, params: Dict[str, Any]) -> Dict[str, Any]:
    settings = _require_settings()
    if not settings.bingx_api_key or not settings.bingx_api_secret:
        LOGGER.debug("Missing BingX credentials; returning empty payload for %s", path)
        return {}

    signed = {
        **params,
        "recvWindow": settings.bingx_recv_window,
        "timestamp": int(time.time() * 1000),
    }
    query = _sign(settings.bingx_api_secret, signed)
    headers = {"X-BX-APIKEY": settings.bingx_api_key}

    async with httpx.AsyncClient(base_url=settings.bingx_base_url, timeout=10.0) as client:
        response = await client.get(f"{path}?{query}", headers=headers)
        LOGGER.debug("BingX signed GET %s: %s", path, response.text)
        response.raise_for_status()
        return response.json()


async def _public_get(path: str, params: Dict[str, Any]) -> Dict[str, Any]:
    settings = _require_settings()
    async with httpx.AsyncClient(base_url=settings.bingx_base_url, timeout=10.0) as client:
        response = await client.get(path, params=params)
        LOGGER.debug("BingX public GET %s: %s", path, response.text)
        response.raise_for_status()
        return response.json()


async def get_positions() -> List[Dict[str, Any]]:
    """Return the open hedge-mode positions from BingX."""
    payload = await _signed_get("/openApi/swap/v2/user/positions", {})
    if not payload:
        return []
    if payload.get("code") != 0:
        LOGGER.warning("Unexpected response while loading positions: %s", payload)
        return []
    return payload.get("data") or []


async def get_mark_price(symbol: str) -> float:
    """Return the current mark price for a contract."""
    data = await _public_get("/openApi/swap/v2/quote/premiumIndex", {"symbol": symbol})
    info = data.get("data") or {}
    price = info.get("markPrice") or info.get("price")
    try:
        return float(price)
    except (TypeError, ValueError):
        LOGGER.debug("Could not parse mark price for %s: %s", symbol, price)
        return 0.0


def _format_usd(value: float) -> str:
    return f"{value:,.2f} USDT"


async def get_account_balance() -> float:
    """Return the USDT futures account balance."""
    payload = await _signed_get("/openApi/swap/v2/user/balance", {})
    if not payload:
        return 0.0
    if payload.get("code") != 0:
        LOGGER.warning("Unexpected response while loading balance: %s", payload)
        return 0.0

    balances = payload.get("data") or []
    for entry in balances:
        asset = (entry.get("asset") or entry.get("currency") or "").upper()
        if asset != "USDT":
            continue

        for key in ("balance", "cashBalance", "availableBalance", "equity"):
            raw_value = entry.get(key)
            if raw_value in (None, ""):
                continue
            try:
                return float(raw_value)
            except (TypeError, ValueError):
                LOGGER.debug("Unable to parse balance value %s for key %s", raw_value, key)
                continue

    return 0.0


async def get_status_summary() -> str:
    """Build a human-readable status summary for Telegram."""
    settings = _require_settings()
    if not settings.bingx_api_key or not settings.bingx_api_secret:
        return (
            "📈 *Status*\n"
            "Keine API-Zugangsdaten hinterlegt – PnL kann nicht geladen werden."
        )

    balance = await get_account_balance()
    positions = await get_positions()
    if not positions:
        return (
            "📈 *Status*\n"
            f"Kontostand: `{_format_usd(balance)}`\n"
            "Keine offenen Positionen.\n"
            "Gesamt-PnL: `0.00 USDT`"
        )

    total_pnl = 0.0
    lines = []
    for position in positions:
        symbol = position.get("symbol", "?")
        side = (position.get("positionSide") or "").upper()
        amount_raw = position.get("positionAmt") or "0"
        entry_raw = position.get("entryPrice") or "0"
        try:
            quantity = abs(float(amount_raw))
            entry_price = float(entry_raw)
        except (TypeError, ValueError):
            LOGGER.debug("Skipping malformed position data: %s", position)
            continue
        if quantity <= 0:
            continue

        mark_price = await get_mark_price(symbol)
        if side == "LONG":
            pnl = (mark_price - entry_price) * quantity
        else:
            pnl = (entry_price - mark_price) * quantity
        total_pnl += pnl
        lines.append(
            "- `{symbol}` {side}  Qty: `{qty}`  Entry: `{entry:.4f}`  Mark: `{mark:.4f}`  PnL: `{pnl}`".format(
                symbol=symbol,
                side=side or "?",
                qty=quantity,
                entry=entry_price,
                mark=mark_price,
                pnl=_format_usd(pnl),
            )
        )

    return (
        "📈 *Status*\n"
        f"Kontostand: `{_format_usd(balance)}`\n"
        "Gesamt-PnL: `{total}`\n\n"
        "*Offene Positionen:*\n{positions}"
    ).format(
        total=_format_usd(total_pnl),
        positions="\n".join(lines) if lines else "Keine offenen Positionen.",
    )
