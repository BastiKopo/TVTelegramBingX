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


class JSONResponse(Response):
    """Simplified JSON response mirroring FastAPI's interface."""

    def __init__(self, content: Any | None = None, status_code: int = 200) -> None:
        super().__init__(content=content, status_code=status_code, media_type="application/json")


__all__ = ["HTMLResponse", "JSONResponse", "Response"]
