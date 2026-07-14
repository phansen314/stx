"""RegistryModal op-assembly — add/set-default/archive across statuses, kinds, transitions.
Daemon-free Pilot test, like test_tui_edges."""
from __future__ import annotations

import pytest

pytest.importorskip("textual")

from textual.app import App  # noqa: E402
from textual.widgets import Button, Checkbox, Input, Select  # noqa: E402

from stxc.models import Kind, Status, Transition  # noqa: E402
from tui.screens.registry import RegistryModal  # noqa: E402

_UNSET = object()

STATUSES = [
    Status(id=1, name="todo", kanban_order=0, is_default=True),
    Status(id=2, name="doing", kanban_order=1),
    Status(id=3, name="done", kanban_order=2, terminal=True),
]
KINDS = [Kind(id=10, name="bug")]
TRANSITIONS = [Transition(id=100, from_status_id=1, to_status_id=2)]
NAMES = {s.id: s.name for s in STATUSES}


class _Host(App):
    def __init__(self, modal: RegistryModal) -> None:
        super().__init__()
        self._modal = modal
        self.result = _UNSET

    def on_mount(self) -> None:
        self.push_screen(self._modal, callback=self._cb)

    def _cb(self, r) -> None:
        self.result = r


async def _run(drive) -> object:
    host = _Host(RegistryModal(STATUSES, KINDS, TRANSITIONS, NAMES))
    async with host.run_test() as pilot:
        await pilot.pause()
        drive(host._modal)
        await pilot.pause()
    return host.result


class TestRegistry:
    @pytest.mark.asyncio
    async def test_add_status_auto_orders_and_flags_terminal(self) -> None:
        def drive(m: RegistryModal) -> None:
            m.query_one("#reg-status-name", Input).value = "review"
            m.query_one("#reg-status-terminal", Checkbox).value = True
            m._add_status()

        # next order = max(0,1,2)+1 = 3
        assert await _run(drive) == {"op": "add_status", "name": "review", "kanban_order": 3, "terminal": True}

    @pytest.mark.asyncio
    async def test_archive_button_ids_in_compose_order(self) -> None:
        # todo(default) → only archive = reg-btn-0; doing → default reg-btn-1, archive reg-btn-2
        def archive_todo(m: RegistryModal) -> None:
            m.query_one("#reg-btn-0", Button).press()

        assert await _run(archive_todo) == {"op": "archive_status", "status_id": 1}

    @pytest.mark.asyncio
    async def test_set_default_on_non_default_status(self) -> None:
        def set_doing_default(m: RegistryModal) -> None:
            m.query_one("#reg-btn-1", Button).press()

        assert await _run(set_doing_default) == {"op": "set_default", "status_id": 2}

    @pytest.mark.asyncio
    async def test_add_transition_maps_selects(self) -> None:
        def drive(m: RegistryModal) -> None:
            m.query_one("#reg-trans-from", Select).value = 2
            m.query_one("#reg-trans-to", Select).value = 3
            m._add_transition()

        assert await _run(drive) == {"op": "add_transition", "from": 2, "to": 3}

    @pytest.mark.asyncio
    async def test_add_transition_rejects_same_endpoints(self) -> None:
        def drive(m: RegistryModal) -> None:
            m.query_one("#reg-trans-from", Select).value = 2
            m.query_one("#reg-trans-to", Select).value = 2
            m._add_transition()

        assert await _run(drive) is _UNSET  # blocked, no dismiss

    @pytest.mark.asyncio
    async def test_add_kind(self) -> None:
        def drive(m: RegistryModal) -> None:
            m.query_one("#reg-kind-name", Input).value = "feature"
            m._add_kind()

        assert await _run(drive) == {"op": "add_kind", "name": "feature"}
