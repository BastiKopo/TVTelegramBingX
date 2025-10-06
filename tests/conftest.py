"""Pytest configuration for the TVTelegramBingX test suite."""

from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _load_fastapi_shim() -> None:
    if "fastapi" in sys.modules:
        return

    module_path = PROJECT_ROOT / "fastapi" / "__init__.py"
    if not module_path.exists():
        return

    spec = importlib.util.spec_from_file_location("fastapi", module_path)
    if spec and spec.loader:
        module = importlib.util.module_from_spec(spec)
        sys.modules["fastapi"] = module
        spec.loader.exec_module(module)


import importlib
import importlib.util  # noqa: E402  - used by the shim loader

_load_fastapi_shim()


def _load_webhook_server() -> None:
    if "webhook.server" in sys.modules:
        return

    importlib.import_module("webhook.server")


_load_webhook_server()
