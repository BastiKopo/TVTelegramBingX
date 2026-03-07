from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest

pytest.importorskip("telegram")

from tvtelegrambingx.bot.telegram_bot import _extract_webhook_overrides


@pytest.mark.parametrize(
    "payload,expected",
    [
        ({"sl": 1.5, "tp": 2.0}, {"sl_move_percent": 1.5, "tp_move_percent": 2.0}),
        ({"stop_loss": "0", "take_profit": "2.5"}, {"tp_move_percent": 2.5}),
        ({"sl": -1, "tp1": -2}, {}),
        (
            {"sl": 1.5, "sl_move_percent": 3, "tp": 2.0, "tp_move_percent": 4},
            {"sl_move_percent": 3.0, "tp_move_percent": 4.0},
        ),
    ],
)
def test_extract_webhook_overrides_supports_sl_tp_aliases(payload, expected):
    assert _extract_webhook_overrides(payload) == expected
