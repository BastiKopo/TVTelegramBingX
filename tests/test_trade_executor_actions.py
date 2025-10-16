from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest

from tvtelegrambingx.utils.actions import canonical_action


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("LONG_BUY", "LONG_BUY"),
        ("long", "LONG_BUY"),
        ("Long Buy", "LONG_BUY"),
        ("long-open", "LONG_OPEN"),
        ("LONG/BUY", "LONG_BUY"),
        ("SHORT", "SHORT_SELL"),
        ("short sell", "SHORT_SELL"),
        ("short-buy", "SHORT_BUY"),
        ("close short", "SHORT_BUY"),
        ("SELL", "SHORT_SELL"),
        ("Long Close", "LONG_SELL"),
    ],
)
def test_canonical_action_variants(raw, expected):
    assert canonical_action(raw) == expected


def test_canonical_action_invalid():
    assert canonical_action("something unexpected") is None
    assert canonical_action("") is None
    assert canonical_action(None) is None
