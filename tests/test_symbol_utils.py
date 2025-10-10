import pytest

from services.symbols import SymbolValidationError, normalize_symbol


def test_normalize_symbol_handles_various_formats() -> None:
    assert normalize_symbol("BTCUSDT") == "BTC-USDT"
    assert normalize_symbol("btc_usdt") == "BTC-USDT"
    assert normalize_symbol("BINANCE:ETHUSDT") == "ETH-USDT"
    assert normalize_symbol("eth-usdt") == "ETH-USDT"


def test_normalize_symbol_respects_whitelist() -> None:
    whitelist = ("BTC-USDT", "ETH-USDT")
    assert normalize_symbol("btc-usdt", whitelist=whitelist) == "BTC-USDT"
    with pytest.raises(SymbolValidationError):
        normalize_symbol("BNB-USDT", whitelist=whitelist)


def test_normalize_symbol_rejects_invalid_tokens() -> None:
    with pytest.raises(SymbolValidationError):
        normalize_symbol("")
    with pytest.raises(SymbolValidationError):
        normalize_symbol("123")
