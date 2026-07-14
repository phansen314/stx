"""tui/app.py::StxApp._explain — the only daemon-free, UI-free pure function in the TUI.
Importing tui.app requires textual; skip cleanly when it isn't installed."""
from __future__ import annotations

import pytest

pytest.importorskip("textual")

import requests  # noqa: E402

from stxc import StxApiError, StxConnError  # noqa: E402
from tui.app import StxApp  # noqa: E402


class TestExplain:
    def test_version_conflict_is_friendly(self) -> None:
        e = StxApiError(409, {"error": "VersionConflict", "message": "stale"})
        assert StxApp._explain(e) == "changed elsewhere — refreshing"

    def test_other_variants_fall_back_to_str(self) -> None:
        e = StxApiError(422, {"error": "IllegalTransition", "message": "no"})
        assert StxApp._explain(e) == str(e)

    def test_conn_error_is_friendly(self) -> None:
        e = StxConnError(requests.RequestException("connection refused"))
        assert StxApp._explain(e) == "daemon unreachable"
