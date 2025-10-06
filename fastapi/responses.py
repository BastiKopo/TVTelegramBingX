"""Minimal response classes for the FastAPI test shim."""

from dataclasses import dataclass
from typing import Any


@dataclass
class HTMLResponse:
    content: Any | None = None


__all__ = ["HTMLResponse"]
