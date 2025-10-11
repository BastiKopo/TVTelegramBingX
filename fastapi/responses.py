"""Minimal response classes for the FastAPI test shim."""

from dataclasses import dataclass
from typing import Any


@dataclass
class HTMLResponse:
    content: Any | None = None


@dataclass
class Response:
    content: Any | None = None
    status_code: int = 200
    media_type: str | None = None


__all__ = ["HTMLResponse", "Response"]
