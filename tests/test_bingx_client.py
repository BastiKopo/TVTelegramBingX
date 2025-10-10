"""Tests for the BingX API client helpers."""

import asyncio
import json
from decimal import Decimal
from typing import Any

import pytest

from integrations.bingx_client import BingXClient, BingXClientError, calc_order_qty


def test_request_with_fallback_retries_missing_endpoints(monkeypatch) -> None:
    """If BingX removes an endpoint version the client should try the next one."""

    client = BingXClient(api_key="key", api_secret="secret")
    attempts: list[str] = []

    async def fake_request(self, method, path, *, params=None):  # type: ignore[override]
        attempts.append(path)
        if len(attempts) == 1:
            raise BingXClientError("BingX API error 100400: this api is not exist")
        return {"ok": True}

    monkeypatch.setattr(BingXClient, "_request", fake_request)

    async def runner() -> None:
        result = await client.get_margin_summary()
        assert result == {"ok": True}

    asyncio.run(runner())

    assert attempts == [
        "/openApi/swap/v3/user/margin",
        "/openApi/swap/v2/user/margin",
    ]


def test_request_with_fallback_tries_alternate_endpoint(monkeypatch) -> None:
    """If all versions of the primary path are missing, fall back to alternates."""

    client = BingXClient(api_key="key", api_secret="secret")
    attempts: list[str] = []

    async def fake_request(self, method, path, *, params=None):  # type: ignore[override]
        attempts.append(path)
        if "getMargin" in path:
            return {"ok": True}
        raise BingXClientError("BingX API error 100400: this api is not exist")

    monkeypatch.setattr(BingXClient, "_request", fake_request)

    async def runner() -> None:
        result = await client.get_margin_summary()
        assert result == {"ok": True}

    asyncio.run(runner())

    assert attempts[:4] == [
        "/openApi/swap/v3/user/margin",
        "/openApi/swap/v2/user/margin",
        "/openApi/swap/v1/user/margin",
        "/openApi/swap/user/margin",
    ]
    assert "/openApi/v3/swap/user/margin" in attempts
    assert "/openApi/contract/v3/user/margin" in attempts
    assert any(path.endswith("/user/getMargin") for path in attempts)
    assert attempts[-1] == "/openApi/swap/v3/user/getMargin"


def test_request_with_fallback_propagates_other_errors(monkeypatch) -> None:
    """Errors other than missing endpoints should bubble up immediately."""

    client = BingXClient(api_key="key", api_secret="secret")
    attempts: list[str] = []

    async def fake_request(self, method, path, *, params=None):  # type: ignore[override]
        attempts.append(path)
        raise BingXClientError("BingX API error 200001: invalid signature")

    monkeypatch.setattr(BingXClient, "_request", fake_request)

    async def runner() -> None:
        with pytest.raises(BingXClientError):
            await client.get_margin_summary()

    asyncio.run(runner())

    assert attempts == ["/openApi/swap/v3/user/margin"]


def test_set_margin_type_uses_margin_coin(monkeypatch) -> None:
    """Setting the margin type forwards symbol, mode and coin to BingX."""

    client = BingXClient(api_key="key", api_secret="secret")
    captured: dict[str, Any] = {}

    async def fake_request(self, method, paths, *, params=None):  # type: ignore[override]
        captured["method"] = method
        captured["paths"] = paths
        captured["params"] = params
        return {"ok": True}

    monkeypatch.setattr(BingXClient, "_request_with_fallback", fake_request)

    asyncio.run(
        client.set_margin_type(symbol="BTCUSDT", margin_mode="ISOLATED", margin_coin="USDT"),
    )

    assert captured["method"] == "POST"
    assert captured["paths"][0] == "/openApi/swap/v3/user/marginType"
    assert captured["params"]["symbol"] == "BTC-USDT"
    assert captured["params"]["marginType"] == "ISOLATED"
    assert captured["params"]["marginCoin"] == "USDT"


def test_set_leverage_forwards_optional_arguments(monkeypatch) -> None:
    """Leverage updates include margin context when provided."""

    client = BingXClient(api_key="key", api_secret="secret")
    captured: dict[str, Any] = {}

    async def fake_request(self, method, paths, *, params=None):  # type: ignore[override]
        captured["method"] = method
        captured["paths"] = paths
        captured["params"] = params
        return {"ok": True}

    monkeypatch.setattr(BingXClient, "_request_with_fallback", fake_request)

    asyncio.run(
        client.set_leverage(
            symbol="ETHUSDT",
            leverage=7.5,
            margin_mode="ISOLATED",
            margin_coin="USDT",
            side="BUY",
            position_side="LONG",
        ),
    )

    assert captured["method"] == "POST"
    assert captured["paths"][0] == "/openApi/swap/v3/user/leverage"
    assert captured["params"]["symbol"] == "ETH-USDT"
    assert captured["params"]["leverage"] == 7.5
    assert captured["params"]["marginType"] == "ISOLATED"
    assert captured["params"]["marginCoin"] == "USDT"
    assert captured["params"]["side"] == "BUY"
    assert captured["params"]["positionSide"] == "LONG"


def test_place_order_forwards_margin_configuration(monkeypatch) -> None:
    """Order placement forwards leverage and margin configuration to BingX."""

    client = BingXClient(api_key="key", api_secret="secret")
    captured: dict[str, Any] = {}

    async def fake_request(self, method, paths, *, params=None):  # type: ignore[override]
        captured["method"] = method
        captured["paths"] = paths
        captured["params"] = params or {}
        return {"orderId": "1", "status": "FILLED"}

    monkeypatch.setattr(BingXClient, "_request_with_fallback", fake_request)

    asyncio.run(
        client.place_order(
            symbol="BTCUSDT",
            side="BUY",
            quantity=1.25,
            margin_mode="ISOLATED",
            margin_coin="USDT",
            leverage=12,
        )
    )

    assert captured["method"] == "POST"
    assert captured["paths"][0] == "/openApi/swap/v3/trade/order"
    assert captured["params"]["symbol"] == "BTC-USDT"
    assert captured["params"]["marginType"] == "ISOLATED"
    assert captured["params"]["marginCoin"] == "USDT"
    assert captured["params"]["leverage"] == 12


def test_calc_order_qty_handles_notional_and_down_rounding() -> None:
    """Order sizing respects min notional and the configured budget."""

    quantity = calc_order_qty(
        price=25_000,
        margin_usdt=40,
        leverage=5,
        step_size=0.001,
        min_qty=0.001,
        min_notional=10.0,
    )

    exposure = quantity * 25_000
    assert exposure >= 10.0
    assert exposure <= 200.0 + 1e-6

    with pytest.raises(ValueError, match="Margin zu klein"):
        calc_order_qty(
            price=30_000,
            margin_usdt=2.0,
            leverage=3,
            step_size=0.001,
            min_qty=0.01,
            min_notional=15.0,
        )


def test_symbol_normalisation_handles_common_formats() -> None:
    """Symbols are coerced into BingX' futures notation."""

    client = BingXClient(api_key="key", api_secret="secret")

    assert client._normalise_symbol("btcusdt") == "BTC-USDT"
    assert client._normalise_symbol("BINANCE:ethusdt") == "ETH-USDT"
    assert client._normalise_symbol("xrp/usdt") == "XRP-USDT"
    assert client._normalise_symbol("ada_usdc") == "ADA-USDC"


def test_get_symbol_filters_uses_cache(monkeypatch) -> None:
    """Repeated requests for the same symbol reuse cached filters."""

    client = BingXClient(api_key="key", api_secret="secret", symbol_filters_ttl=60)
    attempts: list[str] = []

    async def fake_request(self, method, paths, *, params=None):  # type: ignore[override]
        attempts.append(paths[0])
        return {"filters": {"minQty": 0.001, "stepSize": 0.001}}

    monkeypatch.setattr(BingXClient, "_request_with_fallback", fake_request)

    async def runner() -> None:
        first = await client.get_symbol_filters("BTCUSDT")
        second = await client.get_symbol_filters("BTCUSDT")
        assert first == {"min_qty": 0.001, "step_size": 0.001}
        assert second == first

    asyncio.run(runner())

    assert attempts == ["/openApi/swap/v3/market/symbol-config"]


def test_get_symbol_filters_respects_ttl(monkeypatch) -> None:
    """When the TTL expires the API is queried again."""

    client = BingXClient(api_key="key", api_secret="secret", symbol_filters_ttl=1)
    attempts: list[str] = []
    current_time = 1_000.0

    async def fake_request(self, method, paths, *, params=None):  # type: ignore[override]
        attempts.append(paths[0])
        return {"filters": {"minQty": 0.01, "stepSize": 0.01}}

    monkeypatch.setattr(BingXClient, "_request_with_fallback", fake_request)
    monkeypatch.setattr("integrations.bingx_client.time.monotonic", lambda: current_time)

    async def runner() -> None:
        nonlocal current_time
        await client.get_symbol_filters("ETHUSDT")
        current_time += 5
        await client.get_symbol_filters("ETHUSDT")

    asyncio.run(runner())

    assert attempts == [
        "/openApi/swap/v3/market/symbol-config",
        "/openApi/swap/v3/market/symbol-config",
    ]


def test_sign_parameters_encodes_and_signs_complex_values(monkeypatch) -> None:
    """Special characters are percent encoded before signature creation."""

    client = BingXClient(api_key="key", api_secret="secret")

    monkeypatch.setattr(
        "integrations.bingx_client.time.time", lambda: 1700000000.123
    )

    query_string = client._sign_parameters(
        {
            "symbol": "LTC-USDT",
            "side": "BUY",
            "type": "MARKET",
            "quantity": 1.25,
            "clientOrderId": "tv:abc def",
            "reduceOnly": True,
        }
    )

    assert (
        query_string
        == "clientOrderId=tv%3Aabc%20def&quantity=1.25&recvWindow=30000&reduceOnly=true&"
        "side=BUY&symbol=LTC-USDT&timestamp=1700000000123&type=MARKET&signature="
        "41ba7af5085c160a22bf9544d52403d27a3ff6435943414a77aec1f5966173fc"
    )


def test_sign_parameters_preserves_decimal_precision(monkeypatch) -> None:
    """Float quantities are serialised without binary rounding artefacts."""

    client = BingXClient(api_key="key", api_secret="secret")

    monkeypatch.setattr("integrations.bingx_client.time.time", lambda: 1700000000.0)

    query_string = client._sign_parameters({"quantity": 1.95})

    assert "quantity=1.95" in query_string


def test_sign_parameters_preserves_state_derived_quantities(monkeypatch) -> None:
    """Values parsed from ``state.json`` remain stable during signing."""

    state_payload = json.loads('{"max_trade_size": 1.95}')
    quantity_value = state_payload["max_trade_size"]
    assert isinstance(quantity_value, float)

    client = BingXClient(api_key="key", api_secret="secret")

    monkeypatch.setattr("integrations.bingx_client.time.time", lambda: 1700000000.0)

    query_string = client._sign_parameters({"quantity": quantity_value})

    assert "quantity=1.95" in query_string


def test_sign_parameters_handles_decimal_instances(monkeypatch) -> None:
    """Pre-existing ``Decimal`` values keep their textual representation."""

    client = BingXClient(api_key="key", api_secret="secret")

    monkeypatch.setattr("integrations.bingx_client.time.time", lambda: 1700000000.0)

    query_string = client._sign_parameters({"quantity": Decimal("1.9500")})

    assert "quantity=1.95" in query_string


def test_sign_parameters_respects_custom_recv_window(monkeypatch) -> None:
    """A custom recvWindow is injected unless already provided."""

    client = BingXClient(api_key="key", api_secret="secret", recv_window=45_000)

    monkeypatch.setattr(
        "integrations.bingx_client.time.time", lambda: 1700000000.0
    )

    query_string = client._sign_parameters({"symbol": "BTC-USDT"})

    assert (
        query_string
        == "recvWindow=45000&symbol=BTC-USDT&timestamp=1700000000000&signature="
        "0484e5f598c740a4684cc7eb0ddef70bcce42eee90b4154d18291ed5790a3d9c"
    )
