"""Utilities for generating idempotent BingX client order identifiers."""

from __future__ import annotations

import hashlib
import json
import re
import time
from typing import Mapping

__all__ = ["generate_client_order_id"]

_SANITIZE_PATTERN = re.compile(r"[^a-z0-9]+", re.IGNORECASE)


def _sanitize(text: str) -> str:
    cleaned = _SANITIZE_PATTERN.sub("-", text.strip().lower())
    cleaned = cleaned.strip("-")
    return cleaned or "order"


def _hash_payload(payload: Mapping[str, object] | None) -> str:
    if not payload:
        return "payload"
    def _default(value: object) -> str:
        if isinstance(value, (set, tuple)):
            return sorted(value)
        if isinstance(value, bytes):
            return value.hex()
        return str(value)
    canonical = json.dumps(payload, sort_keys=True, default=_default)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]


def generate_client_order_id(
    alert_id: str | None,
    payload: Mapping[str, object] | None,
    *,
    prefix: str = "tv",
    timestamp: int | None = None,
) -> str:
    """Return a deterministic client order identifier for BingX."""

    ts = timestamp if timestamp is not None else int(time.time() * 1000)
    if alert_id:
        token = _sanitize(alert_id)
    else:
        token = _hash_payload(payload)
    identifier = f"{prefix}::{token}::{ts}"
    return identifier[:64]
