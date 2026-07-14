"""EntityEditModal — result assembly for track (name+description) and workspace (name only), and
the empty-name guard. Daemon-free Pilot test, like test_tui_edges."""
from __future__ import annotations

import pytest

pytest.importorskip("textual")

from textual.app import App  # noqa: E402
from textual.widgets import Input, TextArea  # noqa: E402

from tui.screens.dialogs import EntityEditModal  # noqa: E402
from tui.widgets import MarkdownEditor  # noqa: E402

_UNSET = object()


class _Host(App):
    def __init__(self, modal: EntityEditModal) -> None:
        super().__init__()
        self._modal = modal
        self.result = _UNSET

    def on_mount(self) -> None:
        self.push_screen(self._modal, callback=self._cb)

    def _cb(self, r) -> None:
        self.result = r


async def _run(modal: EntityEditModal, drive) -> object:
    host = _Host(modal)
    async with host.run_test() as pilot:
        await pilot.pause()
        drive(modal)
        await pilot.pause()
    return host.result


class TestEntityEdit:
    @pytest.mark.asyncio
    async def test_track_returns_name_and_description(self) -> None:
        def drive(m: EntityEditModal) -> None:
            m.query_one("#e-name", Input).value = "renamed"
            m.query_one("#e-desc", MarkdownEditor).query_one(TextArea).text = "new desc"
            m.action_save()

        result = await _run(EntityEditModal("Edit track", "old", "olddesc"), drive)
        assert result == {"name": "renamed", "description": "new desc"}

    @pytest.mark.asyncio
    async def test_workspace_returns_name_only(self) -> None:
        def drive(m: EntityEditModal) -> None:
            m.query_one("#e-name", Input).value = "ws2"
            m.action_save()

        result = await _run(EntityEditModal("Edit workspace", "ws1"), drive)
        assert result == {"name": "ws2"}

    @pytest.mark.asyncio
    async def test_no_description_field_when_none(self) -> None:
        from textual.css.query import NoMatches

        def drive(m: EntityEditModal) -> None:
            with pytest.raises(NoMatches):
                m.query_one("#e-desc", Input)
            m.action_cancel()

        await _run(EntityEditModal("Edit workspace", "ws1"), drive)

    @pytest.mark.asyncio
    async def test_empty_name_blocks_dismiss(self) -> None:
        def drive(m: EntityEditModal) -> None:
            m.query_one("#e-name", Input).value = "   "
            m.action_save()

        result = await _run(EntityEditModal("Edit track", "old", "d"), drive)
        assert result is _UNSET  # never dismissed
