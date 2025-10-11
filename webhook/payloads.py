"""Utilities for parsing and normalising TradingView webhook payloads."""

from __future__ import annotations

import json
import re
import time
from typing import Any, Mapping, MutableMapping

from services.symbols import SymbolValidationError, normalize_symbol

__all__ = [
    "DeduplicationCache",
    "build_deduplication_key",
    "safe_parse_tradingview",
]

_KV_SEPARATOR = re.compile(r"[;&\n\r]+")
_KEY_VALUE_SPLITTER = re.compile(r"[=:]", re.ASCII)


class DeduplicationCache:
    """In-memory cache for tracking recently processed payload identifiers."""

    def __init__(self, *, ttl_seconds: float = 30.0) -> None:
        self._ttl = ttl_seconds
        self._entries: dict[str, float] = {}

    def _purge(self, now: float) -> None:
        if not self._entries:
            return
        expired = [key for key, ts in self._entries.items() if now - ts > self._ttl]
        for key in expired:
            self._entries.pop(key, None)

    def seen(self, key: str) -> bool:
        """Return ``True`` if *key* was stored recently and refresh the timestamp."""

        now = time.monotonic()
        self._purge(now)
        if key in self._entries:
            self._entries[key] = now
            return True
        self._entries[key] = now
        return False


def _parse_key_value_payload(raw: str) -> dict[str, Any] | None:
    tokens = [segment.strip() for segment in _KV_SEPARATOR.split(raw) if segment.strip()]
    if not tokens:
        return None

    result: dict[str, Any] = {}
    for token in tokens:
        parts = _KEY_VALUE_SPLITTER.split(token, 1)
        if len(parts) != 2:
            continue
        key = parts[0].strip()
        value = parts[1].strip()
        if not key:
            continue
        result[key] = value

    return result or None


def _coerce_numeric(value: Any) -> Any:
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        token = value.strip()
        if not token:
            return value
        try:
            if re.search(r"[.eE]", token):
                return float(token)
            return int(token)
        except ValueError:
            return value
    return value


def _normalise_symbol_value(value: Any) -> str | None:
    if value is None:
        return None
    candidate = str(value).strip()
    if not candidate:
        return None
    try:
        return normalize_symbol(candidate)
    except SymbolValidationError:
        token = candidate.upper()
        token = token.replace("/", "-").replace("_", "-")
        if ":" in token:
            token = token.rsplit(":", 1)[-1]
        return token or None


def _normalise_action(value: Any) -> str | None:
    if value is None:
        return None
    token = str(value).strip().upper()
    if not token:
        return None
    return token.replace(" ", "_")


def _extract_nested(payload: Mapping[str, Any], key: str) -> Any:
    candidate = payload.get(key)
    if isinstance(candidate, Mapping):
        return candidate
    return None


def _normalise_payload(payload: MutableMapping[str, Any]) -> None:
    strategy = _extract_nested(payload, "strategy") or {}

    symbol_candidates = [
        payload.get("symbol"),
        payload.get("ticker"),
        payload.get("pair"),
        payload.get("market"),
        payload.get("SYMBOL"),
        strategy.get("market"),
        strategy.get("symbol"),
    ]

    for candidate in symbol_candidates:
        normalised = _normalise_symbol_value(candidate)
        if normalised:
            payload["symbol"] = normalised
            break

    action_candidate = (
        payload.get("action")
        or payload.get("intent")
        or payload.get("signal")
        or strategy.get("order_action")
    )
    action_value = _normalise_action(action_candidate)
    if action_value:
        payload["action"] = action_value

    if "qty" not in payload:
        for key in ("quantity", "size", "amount", "positionSize"):
            if key in payload:
                payload["qty"] = payload[key]
                break
    if "qty" in payload:
        payload["qty"] = _coerce_numeric(payload["qty"])

    if "margin_usdt" not in payload:
        for key in ("margin_usdt", "marginUsdt", "margin", "marginAmount", "marginValue"):
            if key in payload:
                payload["margin_usdt"] = payload[key]
                break
    if "margin_usdt" in payload:
        payload["margin_usdt"] = _coerce_numeric(payload["margin_usdt"])

    if "lev" not in payload:
        for key in ("lev", "leverage", "lev_value", "levValue"):
            if key in payload:
                payload["lev"] = payload[key]
                break
    if "lev" in payload:
        payload["lev"] = _coerce_numeric(payload["lev"])

    if "alert_id" not in payload:
        for key in ("alert_id", "alertId", "id"):
            if key in payload:
                payload["alert_id"] = str(payload[key])
                break

    if "bar_time" not in payload:
        for key in ("bar_time", "barTime", "time", "timestamp", "ts", "datetime"):
            if key in payload:
                payload["bar_time"] = str(payload[key])
                break
    elif payload.get("bar_time") is not None:
        payload["bar_time"] = str(payload["bar_time"])

    if "side" in payload:
        payload["side"] = _normalise_action(payload["side"]) or payload["side"]

    if "positionSide" in payload:
        payload["positionSide"] = _normalise_action(payload["positionSide"]) or payload[
            "positionSide"
        ]


def safe_parse_tradingview(raw_body: str) -> dict[str, Any]:
    """Return a normalized TradingView payload parsed from *raw_body*."""

    text = (raw_body or "").strip()
    if not text:
        raise ValueError("Empty request body")

    payload: dict[str, Any] | None = None
    try:
        decoded = json.loads(text)
    except json.JSONDecodeError:
        payload = _parse_key_value_payload(text)
    else:
        if isinstance(decoded, Mapping):
            payload = dict(decoded)

    if not isinstance(payload, dict):
        raise ValueError("TradingView payload must be a JSON object or key-value string")

    _normalise_payload(payload)
    return payload


def build_deduplication_key(payload: Mapping[str, Any]) -> str | None:
    """Create a deduplication token derived from *payload* fields."""

    symbol_value = _normalise_symbol_value(
        payload.get("symbol")
        or payload.get("ticker")
        or payload.get("pair")
        or payload.get("market")
    )
    if not symbol_value:
        return None

    action_token = _normalise_action(
        payload.get("action")
        or payload.get("intent")
        or payload.get("side")
        or payload.get("signal")
    )
    if action_token is None:
        action_token = "OTHER"

    if any(token in action_token for token in ("SHORT", "SELL")):
        action_group = "short"
    elif any(token in action_token for token in ("LONG", "BUY")):
        action_group = "long"
    else:
        action_group = action_token

    time_token = (
        payload.get("bar_time")
        or payload.get("barTime")
        or payload.get("time")
        or payload.get("timestamp")
        or payload.get("ts")
        or payload.get("alert_id")
        or payload.get("alertId")
        or payload.get("id")
    )
    if time_token is None:
        return None

    return f"{symbol_value}|{action_group}|{time_token}"

