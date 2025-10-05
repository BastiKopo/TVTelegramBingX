"""Minimal enum definitions used by the tests."""
from __future__ import annotations

from enum import Enum


class ParseMode(str, Enum):
    HTML = "HTML"


__all__ = ["ParseMode"]
