"""Helpers for working with BingX contract metadata."""

from __future__ import annotations

from typing import Any, Mapping

from integrations.bingx_client import normalize_contract_filters as _normalize_contract_filters

__all__ = ["normalize_contract_filters"]


def normalize_contract_filters(contract: Mapping[str, Any]) -> dict[str, str]:
    normalized = _normalize_contract_filters(contract)
    step = str(normalized.get("stepSize"))
    minimum = str(normalized.get("minQty"))
    return {"stepSize": step, "minQty": minimum}
