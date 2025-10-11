"""Utilities for building consistent BingX error messages."""

from __future__ import annotations

from typing import Mapping, Any

from .bingx_constants import BINGX_BASE, PATH_ORDER


def _normalise_method(method: str | None) -> str:
    token = (method or "").strip().upper()
    return token or "GET"


def _normalise_target(url: str | None, path: str | None) -> str:
    if url:
        return url
    if path:
        return path
    return "<unknown>"


def _extract_details(payload: Mapping[str, Any] | str | None) -> tuple[str, str]:
    if isinstance(payload, Mapping):
        code = payload.get("code")
        message = payload.get("msg") or payload.get("message")
        return (
            "" if code in (None, "") else str(code),
            "" if message in (None, "") else str(message),
        )
    if payload in (None, ""):
        return "", ""
    return "", str(payload)


def format_bingx_error(
    method: str | None,
    url: str | None,
    payload: Mapping[str, Any] | str | None,
    *,
    request_path: str | None = None,
) -> str:
    """Return a human readable error string including method and path details."""

    method_token = _normalise_method(method)
    target = _normalise_target(url, request_path)
    code_text, message_text = _extract_details(payload)

    details = (code_text + " " + message_text).strip()
    base = f"Failed to contact BingX: {method_token} {target}"
    if details:
        base = f"{base} → {details}"

    normalised_path = (request_path or "").rstrip("/")
    if normalised_path == PATH_ORDER.rstrip("/"):
        base = (
            f"{base}\nHint: use POST {BINGX_BASE}{PATH_ORDER} with x-www-form-urlencoded."
        )

    return base


__all__ = ["format_bingx_error"]
