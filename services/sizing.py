"""Helpers for translating margin budgets into contract quantities."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_FLOOR

__all__ = ["round_to_step", "qty_from_margin_usdt"]


def _as_decimal(value: Decimal | int | float | str) -> Decimal:
    """Return *value* as :class:`Decimal` preserving precision."""

    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise ValueError("Empty numeric value provided")
        return Decimal(text)
    raise TypeError(f"Unsupported numeric type: {type(value)!r}")


def _format_decimal(value: Decimal) -> str:
    """Return a string representation without exponential notation."""

    quantized = value.normalize()
    text = format(quantized, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def round_to_step(value: Decimal, step: str) -> Decimal:
    """Round ``value`` down to the nearest multiple of ``step``."""

    step_dec = _as_decimal(step)
    if step_dec <= 0:
        raise ValueError("Step size must be greater than zero")

    scaled = (value / step_dec).to_integral_value(rounding=ROUND_FLOOR)
    rounded = scaled * step_dec
    decimals = max(0, -step_dec.normalize().as_tuple().exponent)
    quantizer = Decimal(10) ** -decimals
    return rounded.quantize(quantizer, rounding=ROUND_FLOOR)


def qty_from_margin_usdt(
    margin_usdt: str | int | float | Decimal,
    leverage: int,
    price_usdt: str | int | float | Decimal,
    step: str,
    *,
    min_qty: str | int | float | Decimal | None = None,
    min_notional: str | int | float | Decimal | None = None,
) -> str:
    """Return the contract quantity derived from a USDT margin budget."""

    try:
        margin_value = _as_decimal(margin_usdt)
        price_value = _as_decimal(price_usdt)
    except (TypeError, InvalidOperation) as exc:
        raise ValueError("Invalid margin/price value") from exc

    if price_value <= 0:
        raise ValueError("Invalid margin/price/leverage")
    if margin_value <= 0:
        raise ValueError("Invalid margin/price/leverage")
    if leverage <= 0:
        raise ValueError("Invalid margin/price/leverage")

    leverage_dec = Decimal(int(leverage))
    raw_qty = (margin_value * leverage_dec) / price_value
    qty = round_to_step(raw_qty, step)

    if qty <= 0:
        raise ValueError("Quantity rounded to zero")

    if min_qty is not None:
        try:
            min_qty_value = _as_decimal(min_qty)
        except (TypeError, InvalidOperation) as exc:
            raise ValueError("Invalid minimum quantity") from exc
        if qty < min_qty_value:
            raise ValueError("Quantity below minimum size")

    if min_notional is not None:
        try:
            min_notional_value = _as_decimal(min_notional)
        except (TypeError, InvalidOperation) as exc:
            raise ValueError("Invalid minimum notional") from exc
        if qty * price_value < min_notional_value:
            raise ValueError("Quantity below minimum notional")

    return _format_decimal(qty)
