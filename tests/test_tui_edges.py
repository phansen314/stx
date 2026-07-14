"""EdgeModal op-assembly — direction mapping for add, and the remove-button wiring. Daemon-free:
mount the modal in a tiny host App via Textual's Pilot and assert the op dict it dismisses with."""
from __future__ import annotations

import pytest

pytest.importorskip("textual")

from textual.app import App  # noqa: E402
from textual.widgets import Button, Input, Select  # noqa: E402

from stxc.models import Task  # noqa: E402
from tui.screens.edges import EdgeModal  # noqa: E402

_UNSET = object()


def _task(tid: int, title: str = "t") -> Task:
    return Task(id=tid, title=title)


class _Host(App):
    def __init__(self, modal: EdgeModal) -> None:
        super().__init__()
        self._modal = modal
        self.result = _UNSET

    def on_mount(self) -> None:
        self.push_screen(self._modal, callback=self._cb)

    def _cb(self, r) -> None:
        self.result = r


async def _run(modal: EdgeModal, drive) -> object:
    host = _Host(modal)
    async with host.run_test() as pilot:
        await pilot.pause()
        drive(modal)
        await pilot.pause()
    return host.result


NO_EDGES = {"blocksIn": [], "blocksOut": [], "relates": []}


class TestAdd:
    @pytest.mark.asyncio
    async def test_blocks_out_maps_self_to_source(self) -> None:
        def drive(m: EdgeModal) -> None:
            m.query_one("#e-type", Select).value = "blocks_out"
            m.query_one("#e-target", Select).value = 8
            m._do_add()

        result = await _run(EdgeModal(_task(5, "me"), NO_EDGES, [_task(7), _task(8)]), drive)
        assert result == {"op": "add_blocks", "source": 5, "target": 8}

    @pytest.mark.asyncio
    async def test_blocks_in_flips_direction(self) -> None:
        def drive(m: EdgeModal) -> None:
            m.query_one("#e-type", Select).value = "blocks_in"
            m.query_one("#e-target", Select).value = 7
            m._do_add()

        result = await _run(EdgeModal(_task(5, "me"), NO_EDGES, [_task(7), _task(8)]), drive)
        assert result == {"op": "add_blocks", "source": 7, "target": 5}

    @pytest.mark.asyncio
    async def test_relates_carries_kind(self) -> None:
        def drive(m: EdgeModal) -> None:
            m.query_one("#e-type", Select).value = "relates"
            m.query_one("#e-target", Select).value = 8
            m.query_one("#e-kind", Input).value = "mentions"
            m._do_add()

        result = await _run(EdgeModal(_task(5), NO_EDGES, [_task(8)]), drive)
        assert result == {"op": "add_relates", "kind": "mentions", "source": 5, "target": 8}

    @pytest.mark.asyncio
    async def test_no_target_shows_error_and_does_not_dismiss(self) -> None:
        def drive(m: EdgeModal) -> None:
            m._do_add()  # target left blank

        result = await _run(EdgeModal(_task(5), NO_EDGES, [_task(8)]), drive)
        assert result is _UNSET  # never dismissed


class TestRemove:
    @pytest.mark.asyncio
    async def test_blocked_by_remove_targets_self(self) -> None:
        # task 5 is blocked by 7 -> remove edge is (source=7, target=5)
        detail = {"blocksIn": [7], "blocksOut": [], "relates": []}

        def drive(m: EdgeModal) -> None:
            m.query_one("#edge-rm-0", Button).press()

        result = await _run(EdgeModal(_task(5), detail, [_task(7)]), drive)
        assert result == {"op": "remove_blocks", "source": 7, "target": 5}

    @pytest.mark.asyncio
    async def test_relates_remove_uses_stored_direction(self) -> None:
        # incoming relate: other(9) is source, self(5) is target
        detail = {"blocksIn": [], "blocksOut": [],
                  "relates": [{"kind": "mentions", "otherTaskId": 9, "outgoing": False}]}

        def drive(m: EdgeModal) -> None:
            m.query_one("#edge-rm-0", Button).press()

        result = await _run(EdgeModal(_task(5), detail, [_task(9)]), drive)
        assert result == {"op": "remove_relates", "kind": "mentions", "source": 9, "target": 5}
