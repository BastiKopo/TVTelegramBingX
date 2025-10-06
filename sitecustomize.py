"""Test harness configuration ensuring optional dependencies are stubbed."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _ensure_fastapi_shim() -> None:
    if "fastapi" in sys.modules:
        return

    module_path = Path(__file__).with_name("fastapi") / "__init__.py"
    if not module_path.exists():  # pragma: no cover - guard for packaged installs
        return

    spec = importlib.util.spec_from_file_location("fastapi", module_path)
    if spec and spec.loader:
        module = importlib.util.module_from_spec(spec)
        sys.modules["fastapi"] = module
        spec.loader.exec_module(module)


_ensure_fastapi_shim()
