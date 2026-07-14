"""ConfigModal — live theme preview, save result, cancel-revert, invalid-seconds guard.
Daemon-free Pilot test."""
from __future__ import annotations

import pytest

pytest.importorskip("textual")

from textual.app import App  # noqa: E402
from textual.widgets import Input, Select  # noqa: E402

from tui.screens.config import ConfigModal  # noqa: E402

_UNSET = object()


class _Host(App):
    def __init__(self) -> None:
        super().__init__()
        self.result = _UNSET
        self.modal: ConfigModal | None = None

    def on_mount(self) -> None:
        self.theme = "textual-dark"
        self.modal = ConfigModal("textual-dark", sorted(self.available_themes), 2.0)
        self.push_screen(self.modal, callback=self._cb)

    def _cb(self, r) -> None:
        self.result = r


async def _run(drive):
    """drive(host, modal, pilot) — may await; Select.Changed is async so pause after setting it."""
    host = _Host()
    async with host.run_test() as pilot:
        await pilot.pause()
        await drive(host, host.modal, pilot)
        await pilot.pause()
    return host


class TestConfigModal:
    @pytest.mark.asyncio
    async def test_theme_select_applies_live(self) -> None:
        async def drive(host, m, pilot) -> None:
            m.query_one("#cfg-theme", Select).value = "nord"
            await pilot.pause()

        host = await _run(drive)
        assert host.theme == "nord"  # applied live before any save

    @pytest.mark.asyncio
    async def test_save_returns_theme_and_refresh(self) -> None:
        async def drive(host, m, pilot) -> None:
            m.query_one("#cfg-theme", Select).value = "gruvbox"
            m.query_one("#cfg-refresh", Input).value = "4.5"
            m.action_save()

        host = await _run(drive)
        assert host.result == {"theme": "gruvbox", "refresh_secs": 4.5}

    @pytest.mark.asyncio
    async def test_cancel_reverts_theme(self) -> None:
        async def drive(host, m, pilot) -> None:
            m.query_one("#cfg-theme", Select).value = "dracula"
            await pilot.pause()
            assert host.theme == "dracula"  # previewed live
            m.action_cancel()

        host = await _run(drive)
        assert host.result is None
        assert host.theme == "textual-dark"  # reverted

    @pytest.mark.asyncio
    async def test_invalid_seconds_blocks_dismiss(self) -> None:
        async def drive(host, m, pilot) -> None:
            m.query_one("#cfg-refresh", Input).value = "abc"
            m.action_save()

        host = await _run(drive)
        assert host.result is _UNSET

    @pytest.mark.asyncio
    async def test_nonpositive_seconds_blocks_dismiss(self) -> None:
        async def drive(host, m, pilot) -> None:
            m.query_one("#cfg-refresh", Input).value = "0"
            m.action_save()

        host = await _run(drive)
        assert host.result is _UNSET
