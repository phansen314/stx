from __future__ import annotations

from textual.widgets import Button, Input, Static

from sticky_notes.models import Status
from sticky_notes.service_models import TaskDetail
from sticky_notes.tui.screens.task_metadata import TaskMetadataModal

from helpers import ModalTestApp


def make_detail(metadata: dict[str, str] | None = None) -> TaskDetail:
    return TaskDetail(
        id=1,
        workspace_id=1,
        title="Test task",
        project_id=None,
        description=None,
        status_id=1,
        priority=1,
        due_date=None,
        position=0,
        archived=False,
        created_at=0,
        start_date=None,
        finish_date=None,
        group_id=None,
        metadata=metadata if metadata is not None else {},
        status=Status(id=1, workspace_id=1, name="Todo", archived=False, created_at=0),
        project=None,
        group=None,
        blocked_by=(),
        blocks=(),
        history=(),
        tags=(),
    )


def _make_app(metadata: dict[str, str] | None = None) -> ModalTestApp:
    return ModalTestApp(TaskMetadataModal(make_detail(metadata)))


class TestCompose:
    async def test_empty_metadata_shows_one_blank_row(self):
        app = _make_app({})
        async with app.run_test() as pilot:
            modal = app.screen
            rows = modal.query(".metadata-row")
            assert len(rows) == 1
            key = rows.first().query_one(".metadata-key", Input).value
            value = rows.first().query_one(".metadata-value", Input).value
            assert key == ""
            assert value == ""

    async def test_existing_metadata_populates_rows(self):
        app = _make_app({"branch": "feat/x", "jira": "PROJ-1"})
        async with app.run_test() as pilot:
            modal = app.screen
            rows = modal.query(".metadata-row")
            assert len(rows) == 2
            pairs = sorted(
                (
                    r.query_one(".metadata-key", Input).value,
                    r.query_one(".metadata-value", Input).value,
                )
                for r in rows
            )
            assert pairs == [("branch", "feat/x"), ("jira", "PROJ-1")]

    async def test_header_shows_task_num_and_title(self):
        app = _make_app()
        async with app.run_test() as pilot:
            modal = app.screen
            header = modal.query_one(".modal-id", Static)
            rendered = str(header.render())
            assert "task-0001" in rendered
            assert "Test task" in rendered


class TestDynamicRows:
    async def test_add_row_appends_blank_row(self):
        app = _make_app({"a": "1"})
        async with app.run_test() as pilot:
            modal = app.screen
            assert len(modal.query(".metadata-row")) == 1
            add_btn = modal.query_one("#metadata-add", Button)
            await modal._on_add_row(Button.Pressed(add_btn))
            await pilot.pause()
            rows = modal.query(".metadata-row")
            assert len(rows) == 2
            last = rows.nodes[-1]
            assert last.query_one(".metadata-key", Input).value == ""
            assert last.query_one(".metadata-value", Input).value == ""

    async def test_delete_row_removes_row(self):
        app = _make_app({"a": "1", "b": "2"})
        async with app.run_test() as pilot:
            modal = app.screen
            assert len(modal.query(".metadata-row")) == 2
            del_btn = modal.query(".metadata-delete").first()
            modal._on_delete_row(Button.Pressed(del_btn))
            await pilot.pause()
            assert len(modal.query(".metadata-row")) == 1


class TestSave:
    async def test_save_no_changes_dismisses_none(self):
        app = _make_app({"branch": "feat/x"})
        async with app.run_test() as pilot:
            app.screen.action_save()
            await pilot.pause()
            assert app.result is None

    async def test_save_empty_metadata_unchanged_dismisses_none(self):
        app = _make_app({})
        async with app.run_test() as pilot:
            app.screen.action_save()
            await pilot.pause()
            assert app.result is None

    async def test_save_with_new_key_dismisses_with_full_dict(self):
        app = _make_app({"a": "1"})
        async with app.run_test() as pilot:
            modal = app.screen
            add_btn = modal.query_one("#metadata-add", Button)
            await modal._on_add_row(Button.Pressed(add_btn))
            await pilot.pause()
            rows = modal.query(".metadata-row")
            new_row = rows.nodes[-1]
            new_row.query_one(".metadata-key", Input).value = "b"
            new_row.query_one(".metadata-value", Input).value = "2"
            modal.action_save()
            await pilot.pause()
            assert app.result == {"task_id": 1, "metadata": {"a": "1", "b": "2"}}

    async def test_save_with_deleted_key_dismisses_with_remaining(self):
        app = _make_app({"a": "1", "b": "2"})
        async with app.run_test() as pilot:
            modal = app.screen
            del_btn = modal.query(".metadata-delete").first()
            modal._on_delete_row(Button.Pressed(del_btn))
            await pilot.pause()
            modal.action_save()
            await pilot.pause()
            assert app.result is not None
            assert app.result["task_id"] == 1
            assert len(app.result["metadata"]) == 1

    async def test_save_updated_value_dismisses_with_new_value(self):
        app = _make_app({"branch": "feat/old"})
        async with app.run_test() as pilot:
            modal = app.screen
            row = modal.query(".metadata-row").first()
            row.query_one(".metadata-value", Input).value = "feat/new"
            modal.action_save()
            await pilot.pause()
            assert app.result == {
                "task_id": 1,
                "metadata": {"branch": "feat/new"},
            }

    async def test_blank_row_among_entries_is_stripped(self):
        app = _make_app({"a": "1"})
        async with app.run_test() as pilot:
            modal = app.screen
            add_btn = modal.query_one("#metadata-add", Button)
            await modal._on_add_row(Button.Pressed(add_btn))
            await pilot.pause()
            # Add a real row after the blank one.
            add_btn = modal.query_one("#metadata-add", Button)
            await modal._on_add_row(Button.Pressed(add_btn))
            await pilot.pause()
            rows = modal.query(".metadata-row")
            last = rows.nodes[-1]
            last.query_one(".metadata-key", Input).value = "c"
            last.query_one(".metadata-value", Input).value = "3"
            modal.action_save()
            await pilot.pause()
            assert app.result == {"task_id": 1, "metadata": {"a": "1", "c": "3"}}


class TestValidation:
    async def test_value_without_key_shows_error(self):
        app = _make_app({})
        async with app.run_test() as pilot:
            modal = app.screen
            row = modal.query(".metadata-row").first()
            row.query_one(".metadata-value", Input).value = "orphan"
            modal.action_save()
            await pilot.pause()
            assert app.result == "NOT_SET"  # not dismissed
            err = modal.query_one("#modal-error", Static)
            assert "value without key" in str(err.render())

    async def test_duplicate_normalized_keys_shows_error(self):
        app = _make_app({"foo": "1"})
        async with app.run_test() as pilot:
            modal = app.screen
            add_btn = modal.query_one("#metadata-add", Button)
            await modal._on_add_row(Button.Pressed(add_btn))
            await pilot.pause()
            rows = modal.query(".metadata-row")
            new_row = rows.nodes[-1]
            new_row.query_one(".metadata-key", Input).value = "FOO"
            new_row.query_one(".metadata-value", Input).value = "2"
            modal.action_save()
            await pilot.pause()
            assert app.result == "NOT_SET"
            err = modal.query_one("#modal-error", Static)
            assert "duplicate" in str(err.render())

    async def test_escape_dismisses_none(self):
        app = _make_app({"a": "1"})
        async with app.run_test() as pilot:
            await pilot.press("escape")
            assert app.result is None
