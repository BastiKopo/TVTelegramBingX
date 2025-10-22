from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest

pytest.importorskip("fastapi")

from tvtelegrambingx.webhook.server import _iter_actions


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("LONG_BUY", ["LONG_BUY"]),
        ("long_buy, short_sell", ["LONG_BUY", "SHORT_SELL"]),
        (["long_buy", "short_buy"], ["LONG_BUY", "SHORT_BUY"]),
        ("long_buy short_buy", ["LONG_BUY", "SHORT_BUY"]),
        ("long_buy;short_sell", ["LONG_BUY", "SHORT_SELL"]),
        (None, []),
    ],
)
def test_iter_actions_variants(raw, expected):
    assert list(_iter_actions(raw)) == expected
