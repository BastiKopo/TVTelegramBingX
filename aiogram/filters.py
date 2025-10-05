"""Minimal filters stub."""
from __future__ import annotations


class Command:
    def __init__(self, commands: list[str] | tuple[str, ...]) -> None:
        self.commands = list(commands)


__all__ = ["Command"]
