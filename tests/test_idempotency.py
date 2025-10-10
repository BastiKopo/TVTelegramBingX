import re

from services.idempotency import generate_client_order_id


def test_generate_client_order_id_uses_alert_id() -> None:
    client_id = generate_client_order_id("alert-123", {"symbol": "BTC-USDT"}, timestamp=1700000000000)
    assert client_id.startswith("tv::alert-123")
    assert client_id.endswith("1700000000000")


def test_generate_client_order_id_hashes_payload_when_missing_alert_id() -> None:
    client_id = generate_client_order_id(None, {"symbol": "BTC-USDT", "side": "BUY"}, timestamp=1700000000000)
    pattern = re.compile(r"^tv::[a-z0-9-]+::1700000000000$")
    assert pattern.match(client_id)
