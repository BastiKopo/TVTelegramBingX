"""Validation helpers to ensure BingX requests hit the documented endpoints."""

from __future__ import annotations

from .bingx_constants import PATH_ORDER

_CANONICAL_BASE = "https://open-api.bingx.com"


def assert_bingx_base(base_url: str) -> None:
    """Raise ``ValueError`` when *base_url* deviates from the official host."""

    candidate = (base_url or "").rstrip("/")
    if candidate != _CANONICAL_BASE:
        raise ValueError(
            "Wrong BingX base URL configured: "
            f"{candidate or '<empty>'} (must be {_CANONICAL_BASE})"
        )


def assert_order_path(path: str) -> None:
    """Raise ``ValueError`` when *path* does not match the futures order route."""

    if path != PATH_ORDER:
        raise ValueError(
            f"Wrong BingX order path: {path or '<empty>'} (must be {PATH_ORDER})"
        )


__all__ = ["assert_bingx_base", "assert_order_path"]
