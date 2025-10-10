import pytest

from services.order_mapping import OrderMapping, map_action


@pytest.mark.parametrize(
    "action,mode,expected",
    [
        ("LONG_OPEN", "hedge", OrderMapping("BUY", "LONG", False)),
        ("LONG_CLOSE", "hedge", OrderMapping("SELL", "LONG", True)),
        ("SHORT_OPEN", "hedge", OrderMapping("SELL", "SHORT", False)),
        ("SHORT_CLOSE", "hedge", OrderMapping("BUY", "SHORT", True)),
        ("LONG_OPEN", "oneway", OrderMapping("BUY", "BOTH", False)),
        ("SHORT_CLOSE", "oneway", OrderMapping("BUY", "BOTH", True)),
    ],
)
def test_map_action_returns_expected_mapping(action: str, mode: str, expected: OrderMapping) -> None:
    assert map_action(action, position_mode=mode) == expected


def test_map_action_rejects_unknown_action() -> None:
    with pytest.raises(ValueError):
        map_action("UNKNOWN", position_mode="hedge")
