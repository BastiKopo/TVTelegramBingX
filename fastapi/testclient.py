"""Very small TestClient compatible with the FastAPI shim used in tests."""

from __future__ import annotations

import asyncio
import json as _json
from dataclasses import dataclass
from typing import Any, Dict

from . import FastAPI, HTTPException, Request
from .responses import Response


@dataclass
class _Response:
    status_code: int
    text: str

    def json(self) -> Any:
        try:
            return _json.loads(self.text)
        except _json.JSONDecodeError:
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
            detail = exc.detail
            if isinstance(detail, (dict, list)):
                text = _json.dumps(detail)
            else:
                text = "" if detail is None else str(detail)
            return _Response(status_code=exc.status_code, text=text)

        if isinstance(result, tuple):
            result, _ = result

        if isinstance(result, Response):
            content = result.content
            if isinstance(content, (dict, list)):
                return _Response(status_code=result.status_code, text=_json.dumps(content))
            if isinstance(content, bytes):
                return _Response(status_code=result.status_code, text=content.decode("utf-8"))
            return _Response(status_code=result.status_code, text="" if content is None else str(content))

        if isinstance(result, (dict, list)):
            return _Response(status_code=200, text=_json.dumps(result))

        return _Response(status_code=200, text=str(result))

    def post(self, path: str, json: Any | None = None, headers: Dict[str, str] | None = None) -> _Response:
        body_bytes = b""
        if json is not None:
            body_bytes = _json.dumps(json).encode("utf-8")

        request = Request(json_data=json, body=body_bytes, headers=headers)

        try:
            result = self._run(self.app._dispatch("POST", path, request))
        except HTTPException as exc:
            detail = exc.detail
            if isinstance(detail, (dict, list)):
                text = _json.dumps(detail)
            else:
                text = "" if detail is None else str(detail)
            return _Response(status_code=exc.status_code, text=text)

        if isinstance(result, tuple):
            result, _ = result

        if isinstance(result, Response):
            content = result.content
            if isinstance(content, (dict, list)):
                return _Response(status_code=result.status_code, text=_json.dumps(content))
            if isinstance(content, bytes):
                return _Response(status_code=result.status_code, text=content.decode("utf-8"))
            return _Response(status_code=result.status_code, text="" if content is None else str(content))

        if isinstance(result, (dict, list)):
            return _Response(status_code=200, text=_json.dumps(result))

        return _Response(status_code=200, text=str(result))
