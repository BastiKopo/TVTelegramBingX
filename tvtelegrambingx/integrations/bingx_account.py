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
    if not _is_success_code(payload.get("code")):
        LOGGER.warning("Unexpected response while loading positions: %s", payload)
        return []
    return payload.get("data") or []


async def get_mark_price(symbol: str) -> float:
    """Return the current mark price for a contract."""
    data = await _public_get("/openApi/swap/v2/quote/premiumIndex", {"symbol": symbol})
    info = data.get("data") if isinstance(data, dict) else None

    if isinstance(info, dict) and "list" in info and isinstance(info["list"], list):
        info = info["list"]

    if isinstance(info, list):
        selected = None
        for entry in info:
            if not isinstance(entry, dict):
                continue
            if entry.get("symbol") == symbol:
                selected = entry
                break
            if selected is None and (entry.get("markPrice") or entry.get("price")):
                selected = entry
        info = selected

    price = (info or {}).get("markPrice") or (info or {}).get("price")
    try:
        return float(price)
    except (TypeError, ValueError):
        LOGGER.debug("Could not parse mark price for %s from payload: %s", symbol, data)
        return 0.0


def _parse_kline_entry(entry: Any) -> Optional[Dict[str, float]]:
    if isinstance(entry, dict):
        high = entry.get("high") or entry.get("h")
        low = entry.get("low") or entry.get("l")
        close = entry.get("close") or entry.get("c")
        timestamp = (
            entry.get("time")
            or entry.get("timestamp")
            or entry.get("t")
            or entry.get("openTime")
        )
    elif isinstance(entry, (list, tuple)) and len(entry) >= 5:
        timestamp = entry[0]
        high = entry[2]
        low = entry[3]
        close = entry[4]
    else:
        return None

    try:
        return {
            "timestamp": float(timestamp),
            "high": float(high),
            "low": float(low),
            "close": float(close),
        }
    except (TypeError, ValueError):
        return None


async def get_klines(symbol: str, *, interval: str, limit: int) -> List[Dict[str, float]]:
    payload = await _public_get(
        "/openApi/swap/v2/quote/kline",
        {"symbol": symbol, "interval": interval, "limit": limit},
    )
    if not isinstance(payload, dict):
        return []

    data = payload.get("data") or payload.get("list") or payload.get("candles")
    if isinstance(data, dict):
        data = data.get("list") or data.get("data")

    if not isinstance(data, list):
        return []

    parsed: List[Dict[str, float]] = []
    for entry in data:
        item = _parse_kline_entry(entry)
        if item is None:
            continue
        parsed.append(item)
    return parsed


def _format_usd(value: float) -> str:
    return f"{value:,.2f} USDT"


async def get_account_balance() -> float:
    """Return the USDT futures account balance."""
    payload = await _signed_get("/openApi/swap/v2/user/balance", {})
    if not payload:
        return 0.0
    if not _is_success_code(payload.get("code")):
        LOGGER.warning("Unexpected response while loading balance: %s", payload)
        return 0.0

    raw_data = payload.get("data") or []

    if isinstance(raw_data, dict):
        # Some BingX responses wrap the balance info in additional keys.
        candidates: List[Dict[str, Any]] = [raw_data]
        for key in (
            "balance",
            "balances",
            "list",
            "accountBalanceList",
            "balanceList",
            "data",
        ):
            value = raw_data.get(key)
            if isinstance(value, dict):
                candidates.append(value)
            elif isinstance(value, list):
                candidates.extend(entry for entry in value if isinstance(entry, dict))
        balances: List[Dict[str, Any]] = [entry for entry in candidates if isinstance(entry, dict)]
    elif isinstance(raw_data, list):
        balances = [entry for entry in raw_data if isinstance(entry, dict)]
    else:
        LOGGER.debug("Unsupported balance payload type: %r", raw_data)
        balances = []

    for entry in balances:
        asset = (entry.get("asset") or entry.get("currency") or "").upper()
        if asset and asset != "USDT":
            continue

        for key in (
            "balance",
            "cashBalance",
            "availableBalance",
            "equity",
            "availableMargin",
            "walletBalance",
            "available",
        ):
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
