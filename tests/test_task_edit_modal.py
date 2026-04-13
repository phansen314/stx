from __future__ import annotations

from helpers import ModalTestApp
from textual.widgets import Input, Select, Static, TextArea

from stx.models import Group, Status
from stx.service_models import TaskDetail
from stx.tui.model import GroupNode
from stx.tui.screens.task_edit import TaskEditModal


def _group(id: int, title: str) -> Group:
    return Group(
        id=id,
        workspace_id=1,
        title=title,
        description=None,
        parent_id=None,
        position=0,
        archived=False,
        created_at=0,
        metadata={},
    )


def make_detail(**overrides) -> TaskDetail:
    defaults = dict(
        id=1,
        workspace_id=1,
        title="Test task",
        description="desc",
        status_id=1,
        priority=2,
        due_date=None,
        position=0,
        archived=False,
        created_at=0,
        start_date=None,
        finish_date=None,
        group_id=None,
        metadata={},
        status=Status(id=1, workspace_id=1, name="Todo", archived=False, created_at=0),
        group=None,
        edge_sources=(),
        edge_targets=(),
        history=(),
    )
    defaults.update(overrides)
    return TaskDetail(**defaults)


STATUSES = (
    Status(id=1, workspace_id=1, name="Todo", archived=False, created_at=0),
    Status(id=2, workspace_id=1, name="Done", archived=False, created_at=0),
)

GROUP_OPTIONS: list[tuple[str, int]] = [
    ("Frontend", 10),
    ("Frontend > Login", 11),
    ("Backend", 20),
]


def _make_app(
    *,
    group_options: list[tuple[str, int]] = GROUP_OPTIONS,
    **detail_overrides,
) -> ModalTestApp:
    detail = make_detail(**detail_overrides)
    modal = TaskEditModal(detail, STATUSES, group_options)
    return ModalTestApp(modal)


class TestSaveNoChanges:
    async def test_save_no_changes_dismisses_none(self):
        app = _make_app()
        async with app.run_test() as pilot:
            modal = app.screen
            modal.action_save()
            await pilot.pause()
            assert app.result is None

    async def test_cancel_dismisses_none(self):
        app = _make_app()
        async with app.run_test() as pilot:
            await pilot.press("escape")
            assert app.result is None


class TestSaveValidation:
    async def test_empty_title_shows_error(self):
        app = _make_app()
        async with app.run_test() as pilot:
            modal = app.screen
            modal.query_one("#task-edit-title", Input).value = ""
            modal.action_save()
            await pilot.pause()
            error = modal.query_one("#modal-error", Static)
            assert "Title is required" in str(error.render())
            assert app.result == "NOT_SET"

    async def test_invalid_date_shows_error(self):
        app = _make_app()
        async with app.run_test() as pilot:
            modal = app.screen
            modal.query_one("#task-edit-due", Input).value = "not-a-date"
            modal.action_save()
            await pilot.pause()
            error = modal.query_one("#modal-error", Static)
            assert "Invalid date" in str(error.render())
            assert app.result == "NOT_SET"

    async def test_finish_before_start_shows_error(self):
        app = _make_app()
        async with app.run_test() as pilot:
            modal = app.screen
            modal.query_one("#task-edit-start", Input).value = "2026-06-01"
            modal.query_one("#task-edit-finish", Input).value = "2026-05-01"
            modal.action_save()
            await pilot.pause()
            error = modal.query_one("#modal-error", Static)
            assert "Finish date" in str(error.render())
            assert app.result == "NOT_SET"


class TestSaveFieldChanges:
    async def test_title_change(self):
        app = _make_app()
        async with app.run_test() as pilot:
            modal = app.screen
            modal.query_one("#task-edit-title", Input).value = "New title"
            modal.action_save()
            await pilot.pause()
            assert app.result == {"task_id": 1, "changes": {"title": "New title"}}

    async def test_description_change(self):
        app = _make_app()
        async with app.run_test() as pilot:
            modal = app.screen
            textarea = modal.query_one(TextArea)
            textarea.clear()
            textarea.insert("new desc")
            modal.action_save()
            await pilot.pause()
            assert app.result == {"task_id": 1, "changes": {"description": "new desc"}}

    async def test_empty_description_becomes_none(self):
        app = _make_app(description="something")
        async with app.run_test() as pilot:
            modal = app.screen
            textarea = modal.query_one(TextArea)
            textarea.clear()
            modal.action_save()
            await pilot.pause()
            assert app.result == {"task_id": 1, "changes": {"description": None}}

    async def test_status_change(self):
        app = _make_app(status_id=1)
        async with app.run_test() as pilot:
            modal = app.screen
            modal.query_one("#task-edit-status", Select).value = 2
            modal.action_save()
            await pilot.pause()
            assert app.result == {"task_id": 1, "changes": {"status_id": 2}}

    async def test_priority_change(self):
        app = _make_app(priority=2)
        async with app.run_test() as pilot:
            modal = app.screen
            modal.query_one("#task-edit-priority", Select).value = 5
            modal.action_save()
            await pilot.pause()
            assert app.result == {"task_id": 1, "changes": {"priority": 5}}

    async def test_multiple_changes(self):
        app = _make_app()
        async with app.run_test() as pilot:
            modal = app.screen
            modal.query_one("#task-edit-title", Input).value = "Changed"
            modal.query_one("#task-edit-priority", Select).value = 4
            modal.action_save()
            await pilot.pause()
            assert app.result == {
                "task_id": 1,
                "changes": {"title": "Changed", "priority": 4},
            }


class TestGroupSelector:
    async def test_group_pre_selected_from_detail(self):
        app = _make_app(group_id=10)
        async with app.run_test() as pilot:
            modal = app.screen
            group_select = modal.query_one("#task-edit-group", Select)
            assert group_select.value == 10

    async def test_group_select_null_when_unset(self):
        app = _make_app(group_id=None)
        async with app.run_test() as pilot:
            modal = app.screen
            group_select = modal.query_one("#task-edit-group", Select)
            assert group_select.value is Select.NULL

    async def test_assign_group_save_includes_group_id(self):
        app = _make_app(group_id=None)
        async with app.run_test() as pilot:
            modal = app.screen
            modal.query_one("#task-edit-group", Select).value = 11
            modal.action_save()
            await pilot.pause()
            assert app.result == {"task_id": 1, "changes": {"group_id": 11}}

    async def test_unassign_group_save_clears_group_id(self):
        app = _make_app(group_id=10)
        async with app.run_test() as pilot:
            modal = app.screen
            modal.query_one("#task-edit-group", Select).clear()
            modal.action_save()
            await pilot.pause()
            assert app.result == {"task_id": 1, "changes": {"group_id": None}}

    async def test_no_groups_still_renders(self):
        app = _make_app(group_options=[], group_id=None)
        async with app.run_test() as pilot:
            modal = app.screen
            modal.query_one("#task-edit-title", Input).value = "New title"
            modal.action_save()
            await pilot.pause()
            assert app.result == {"task_id": 1, "changes": {"title": "New title"}}
