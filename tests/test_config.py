"""Tests for configuration helpers."""

from __future__ import annotations

import pytest

from config import get_settings


def _missing_env_path(tmp_path):
    """Return a path that does not exist for ``get_settings`` calls."""

    missing = tmp_path / "missing.env"
    assert not missing.exists()
    return str(missing)


def test_get_settings_rejects_invalid_telegram_token(monkeypatch, tmp_path):
    """``get_settings`` should fail fast when the Telegram token is malformed."""

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456789")
    monkeypatch.setenv("BINGX_API_KEY", "key")
    monkeypatch.setenv("BINGX_API_SECRET", "secret")

    with pytest.raises(RuntimeError, match="TELEGRAM_BOT_TOKEN looks invalid"):
        get_settings(dotenv_path=_missing_env_path(tmp_path))


def test_get_settings_supports_file_based_secrets(monkeypatch, tmp_path):
    """Secrets provided via *_FILE variables should be read from disk."""

    token_path = tmp_path / "telegram.token"
    token_path.write_text("123456789:ABCDEF\n")
    api_key_path = tmp_path / "bingx.key"
    api_key_path.write_text("api-key\n")
    api_secret_path = tmp_path / "bingx.secret"
    api_secret_path.write_text("super-secret\n")

    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("BINGX_API_KEY", raising=False)
    monkeypatch.delenv("BINGX_API_SECRET", raising=False)

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN_FILE", str(token_path))
    monkeypatch.setenv("BINGX_API_KEY_FILE", str(api_key_path))
    monkeypatch.setenv("BINGX_API_SECRET_FILE", str(api_secret_path))

    settings = get_settings(dotenv_path=_missing_env_path(tmp_path))

    assert settings.telegram_bot_token == "123456789:ABCDEF"
    assert settings.bingx_api_key == "api-key"
    assert settings.bingx_api_secret == "super-secret"


def test_get_settings_errors_for_missing_secret_file(monkeypatch, tmp_path):
    """A helpful error should be raised when a *_FILE reference is invalid."""

    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN_FILE", str(tmp_path / "missing.token"))
    monkeypatch.setenv("BINGX_API_KEY", "key")
    monkeypatch.setenv("BINGX_API_SECRET", "secret")

    with pytest.raises(RuntimeError, match="TELEGRAM_BOT_TOKEN_FILE"):
        get_settings(dotenv_path=_missing_env_path(tmp_path))
