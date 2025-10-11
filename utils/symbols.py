"""Symbol normalisation helpers shared between Telegram and trading flows."""

from __future__ import annotations

import re

__all__ = ["norm_symbol", "is_symbol"]

_SYM = re.compile(r"^[A-Z]{2,10}-?USDT$", re.IGNORECASE)


def norm_symbol(value: str | None) -> str:
    """Return ``value`` normalised to the ``AAA-USDT`` representation.

    The helper follows the semantics described in the trading playbook: symbols
    are upper-cased, underscores are replaced by dashes, and missing dashes
    before ``USDT`` are inserted automatically.
    """

    token = (value or "").upper().replace("_", "-")
    if token.endswith("USDT") and "-" not in token:
        token = f"{token[:-4]}-USDT"
    return token


def is_symbol(value: str | None) -> bool:
    """Return ``True`` when *value* resembles a tradable symbol."""

    return bool(_SYM.match((value or "").replace("-", "")))
