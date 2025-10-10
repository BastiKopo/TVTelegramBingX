from decimal import Decimal

import pytest

from services.sizing import qty_from_margin_usdt, round_to_step


def test_round_to_step_floors_to_grid() -> None:
    value = Decimal("0.0254")
    assert round_to_step(value, "0.001") == Decimal("0.025")
    assert round_to_step(value, "0.01") == Decimal("0.02")


def test_qty_from_margin_basic_conversion() -> None:
    qty = qty_from_margin_usdt(300, 10, 120_000, "0.001")
    assert qty == "0.025"


def test_qty_from_margin_respects_step_precision() -> None:
    qty = qty_from_margin_usdt("150", 5, "10000", "0.01")
    assert qty == "0.07"


def test_qty_from_margin_rejects_invalid_inputs() -> None:
    with pytest.raises(ValueError):
        qty_from_margin_usdt(0, 10, 120_000, "0.001")
    with pytest.raises(ValueError):
        qty_from_margin_usdt(100, 0, 120_000, "0.001")
    with pytest.raises(ValueError):
        qty_from_margin_usdt(100, 10, 0, "0.001")


def test_qty_from_margin_enforces_minimums() -> None:
    with pytest.raises(ValueError, match="minimum size"):
        qty_from_margin_usdt(20, 1, 4_000, "0.001", min_qty="0.01")
    with pytest.raises(ValueError, match="notional"):
        qty_from_margin_usdt(5, 2, 20_000, "0.0001", min_notional="50")
