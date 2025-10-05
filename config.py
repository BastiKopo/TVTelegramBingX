"""Application configuration utilities."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


def load_dotenv(dotenv_path: Optional[str] = None) -> None:
    """Load environment variables from a ``.env`` file if present.

    Parameters
    ----------
    dotenv_path:
        Optional path to a custom ``.env`` file. Defaults to ``.env`` in the
        project root when not provided.
    """

    path = Path(dotenv_path or ".env")
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        if "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"')
        os.environ.setdefault(key, value)


@dataclass(frozen=True)
class Settings:
    """Container for application-wide configuration values."""

    telegram_bot_token: str


def get_settings(dotenv_path: Optional[str] = None) -> Settings:
    """Return the application settings.

    Loading order:
    1. Existing environment variables.
    2. Variables declared in ``.env`` (without overriding existing values).

    Parameters
    ----------
    dotenv_path:
        Optional path to a custom ``.env`` file.

    Raises
    ------
    RuntimeError
        If required configuration values are missing.
    """

    load_dotenv(dotenv_path=dotenv_path)

    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN is not configured. Set the environment variable or add it to the .env file."
        )

    return Settings(telegram_bot_token=token)


__all__ = ["Settings", "get_settings", "load_dotenv"]
