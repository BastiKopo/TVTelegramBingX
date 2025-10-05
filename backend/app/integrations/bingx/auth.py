"""Signing helpers for BingX REST requests."""
from __future__ import annotations

import hashlib
import hmac
from typing import Mapping
from urllib.parse import urlencode


def build_signature(secret: str, params: Mapping[str, object]) -> str:
    """Return an HMAC SHA256 signature for ``params`` using ``secret``.

    Parameters are sorted alphabetically following the BingX signing rules and
    urlencoded prior to hashing.
    """

    query = urlencode(sorted(((key, str(value)) for key, value in params.items() if value is not None)))
    signature = hmac.new(secret.encode("utf-8"), query.encode("utf-8"), hashlib.sha256).hexdigest()
    return signature


__all__ = ["build_signature"]
