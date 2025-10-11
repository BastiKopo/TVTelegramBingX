"""Tests for configuration helpers."""

from __future__ import annotations

import pytest

from config import get_settings


def test_get_settings_rejects_invalid_telegram_token(monkeypatch, tmp_path):
    """``get_settings`` should fail fast when the Telegram token is malformed."""

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456789")
    monkeypatch.setenv("BINGX_API_KEY", "key")
    monkeypatch.setenv("BINGX_API_SECRET", "secret")

    with pytest.raises(RuntimeError, match="TELEGRAM_BOT_TOKEN looks invalid"):
        get_settings(dotenv_path=str(tmp_path / "missing.env"))
