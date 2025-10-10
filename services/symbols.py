"""Helpers for working with BingX trading symbols."""

from __future__ import annotations

import re
from typing import Collection

__all__ = ["normalize_symbol", "SymbolValidationError"]

_KNOWN_QUOTES = (
    "USDT",
    "USDC",
    "BUSD",
    "USD",
    "BTC",
    "ETH",
)

_SYMBOL_PATTERN = re.compile(r"^[A-Z0-9]{2,}[-_:/]?[A-Z0-9]{2,}$")


class SymbolValidationError(ValueError):
    """Raised when a provided symbol cannot be normalized or validated."""


def _strip_broker_prefix(symbol: str) -> str:
    if ":" not in symbol:
        return symbol
    return symbol.rsplit(":", 1)[-1]


def _split_compact_symbol(symbol: str) -> tuple[str, str] | None:
    for quote in _KNOWN_QUOTES:
        if symbol.endswith(quote) and len(symbol) > len(quote):
            return symbol[: -len(quote)], quote
    if len(symbol) >= 6:
        return symbol[:-4], symbol[-4:]
    return None


def normalize_symbol(symbol: str, *, whitelist: Collection[str] | None = None) -> str:
    """Return ``symbol`` in the ``AAA-BBB`` format required by BingX."""

    if not isinstance(symbol, str):
        raise SymbolValidationError("Symbol must be a string value")

    token = _strip_broker_prefix(symbol.strip().upper())
    token = token.replace("/", "-").replace("_", "-")

    if not token or not _SYMBOL_PATTERN.match(token.replace("-", "")):
        raise SymbolValidationError(f"Ungültiges Symbol: {symbol!r}")

    base: str | None = None
    quote: str | None = None

    if "-" in token:
        parts = [segment for segment in token.split("-") if segment]
        if len(parts) >= 2:
            base, quote = parts[0], parts[1]
    else:
        compact = _split_compact_symbol(token)
        if compact:
            base, quote = compact

    if not base or not quote:
        raise SymbolValidationError(f"Symbol konnte nicht normalisiert werden: {symbol!r}")

    normalized = f"{base}-{quote}"

    if whitelist:
        normalized_whitelist = {item.strip().upper() for item in whitelist if item}
        if normalized not in normalized_whitelist:
            raise SymbolValidationError(
                f"Symbol {normalized} ist nicht in der Whitelist erlaubt."
            )

    return normalized
