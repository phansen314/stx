"""Shared test fixtures for the stx-v3 Python client layer.

The daemon boundary is HTTP, and this sibling-less project has no precedent for mocking it
(the ~/code/stx predecessor talks straight to SQLite). The convention established here: inject
a fake `requests.Session` into `Client.s` (the only network seam, stxc/client.py:28). No daemon,
no sockets — tests assert the exact wire contract the client sends and parses.
"""
from __future__ import annotations

from typing import Any

import pytest
import requests

from stxc import Client


class FakeResponse:
    """Stands in for a `requests.Response`. `json()` raises ValueError when no JSON was set,
    exercising the client's text fallback (stxc/client.py:34)."""

    def __init__(self, status_code: int = 200, json_data: Any = None, text: str = "") -> None:
        self.status_code = status_code
        self._json = json_data
        self.text = text

    def json(self) -> Any:
        if self._json is None:
            raise ValueError("no JSON body")
        return self._json


class FakeSession:
    """Records every call and returns queued FakeResponses (FIFO). Covers both `.request(...)`
    used by `_call` and `.get(...)` used by `ping`."""

    def __init__(self, responses: list[FakeResponse] | None = None, raise_on_get: bool = False,
                 raise_on_request: bool = False) -> None:
        self._responses = list(responses or [])
        self.calls: list[dict[str, Any]] = []
        self.raise_on_get = raise_on_get
        self.raise_on_request = raise_on_request

    def request(self, method: str, url: str, json: Any = None, timeout: Any = None) -> FakeResponse:
        self.calls.append({"method": method, "url": url, "json": json, "timeout": timeout})
        if self.raise_on_request:
            raise requests.RequestException("connection refused")
        return self._responses.pop(0)

    def get(self, url: str, timeout: Any = None) -> FakeResponse:
        self.calls.append({"method": "GET", "url": url, "json": None, "timeout": timeout})
        if self.raise_on_get:
            raise requests.RequestException("connection refused")
        return self._responses.pop(0)

    @property
    def last(self) -> dict[str, Any]:
        return self.calls[-1]


@pytest.fixture
def make_client():
    """Build a Client whose session is a FakeSession primed with `responses`."""

    def _make(responses: list[FakeResponse] | None = None, *, raise_on_get: bool = False,
              raise_on_request: bool = False, base: str = "http://x:8420") -> Client:
        c = Client(base)
        c.s = FakeSession(responses, raise_on_get=raise_on_get, raise_on_request=raise_on_request)
        return c

    return _make


# ── wire-dict factories (camelCase, as the daemon emits) ──────────────────────
def status_dict(**over: Any) -> dict[str, Any]:
    d = {"id": 1, "workspaceId": 1, "name": "todo", "kanbanOrder": 0,
         "terminal": False, "isDefault": True, "archived": False}
    d.update(over)
    return d


def task_dict(**over: Any) -> dict[str, Any]:
    d = {"id": 1, "workspaceId": 1, "segmentId": 1, "statusId": 1, "kindId": None,
         "title": "t", "priority": 0, "version": 0, "archived": False}
    d.update(over)
    return d
