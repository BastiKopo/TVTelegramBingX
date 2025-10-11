"""Quantity helper mirroring the BingX bot behaviour."""

from __future__ import annotations

from decimal import Decimal, ROUND_FLOOR

__all__ = ["qty_from_margin"]


def _floor(value: Decimal, step: Decimal) -> Decimal:
    if step <= 0:
        return value
    return (value / step).to_integral_value(rounding=ROUND_FLOOR) * step


def qty_from_margin(
    margin_usdt: float,
    lev: int,
    mark_price: str,
    step_size: str,
    min_qty: str,
) -> str:
    margin = Decimal(str(margin_usdt))
    leverage = Decimal(str(lev))
    price = Decimal(str(mark_price))
    step = Decimal(str(step_size))
    minimum = Decimal(str(min_qty))

    raw_qty = (margin * leverage) / price
    qty = _floor(raw_qty, step)
    if qty < minimum:
        raise ValueError(f"Margin zu klein: {qty} < minQty {minimum}")
    return f"{qty.normalize():f}"
