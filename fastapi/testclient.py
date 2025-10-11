"""Very small TestClient compatible with the FastAPI shim used in tests."""

from __future__ import annotations

import asyncio
import json as _json
from dataclasses import dataclass
from typing import Any, Dict

from . import FastAPI, HTTPException, Request


@dataclass
class _Response:
    status_code: int
    text: str

    def json(self) -> Any:
        try:
            return json.loads(self.text)
        except json.JSONDecodeError:
            return self.text


class TestClient:
    """Extremely small test client for the shimmed FastAPI app."""

    def __init__(self, app: FastAPI) -> None:
        self.app = app
        
    __test__ = False  # prevent pytest from treating this as a test case

    def _run(self, coro: Any) -> Any:
        if asyncio.iscoroutine(coro):
            return asyncio.run(coro)
        return coro

    def get(self, path: str, headers: Dict[str, str] | None = None) -> _Response:
        try:
            result = self._run(self.app._dispatch("GET", path, Request(headers=headers)))
        except HTTPException as exc:  # pragma: no cover - defensive fallback
            return _Response(status_code=exc.status_code, text=str(exc.detail))
        return _Response(status_code=200, text=str(result))

    def post(self, path: str, json: Any | None = None, headers: Dict[str, str] | None = None) -> _Response:
        body_bytes = b""
        if json is not None:
            body_bytes = _json.dumps(json).encode("utf-8")

        request = Request(json_data=json, body=body_bytes, headers=headers)

        try:
            result = self._run(self.app._dispatch("POST", path, request))
        except HTTPException as exc:
            return _Response(status_code=exc.status_code, text=str(exc.detail))
        if isinstance(result, (dict, list)):
            return _Response(status_code=200, text=_json.dumps(result))
        return _Response(status_code=200, text=str(result))
