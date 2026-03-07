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
        (
            {
                "sl": 1.5,
                "tp1": 1.0,
                "tp1_sell": 25,
                "tp2": 2.0,
                "tp2_sell": 25,
                "tp3": 3.0,
                "tp3_sell": 25,
                "tp4": 4.0,
                "tp4_sell": 25,
            },
            {
                "sl_move_percent": 1.5,
                "tp_move_percent": 1.0,
                "tp_sell_percent": 25.0,
                "tp2_move_percent": 2.0,
                "tp2_sell_percent": 25.0,
                "tp3_move_percent": 3.0,
                "tp3_sell_percent": 25.0,
                "tp4_move_percent": 4.0,
                "tp4_sell_percent": 25.0,
            },
        ),
        ({"stop_loss": "0", "take_profit": "2.5", "tp_sell": "150"}, {"tp_move_percent": 2.5}),
        ({"sl": -1, "tp1": -2, "tp2_sell": 0}, {}),
        (
            {
                "sl": 1.5,
                "sl_move_percent": 3,
                "tp1": 2.0,
                "tp_move_percent": 4,
                "tp1_sell": 20,
                "tp_sell_percent": 35,
            },
            {
                "sl_move_percent": 3.0,
                "tp_move_percent": 4.0,
                "tp_sell_percent": 35.0,
            },
        ),
    ],
)
def test_extract_webhook_overrides_supports_tp_ladder_aliases(payload, expected):
    assert _extract_webhook_overrides(payload) == expected
