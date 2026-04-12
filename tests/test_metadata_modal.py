from __future__ import annotations

from helpers import ModalTestApp
from textual.widgets import Button, Input, Static

from sticky_notes.tui.screens.metadata import MetadataModal


def _make_app(
    metadata: dict[str, str] | None = None,
    *,
    display_title: str = "Metadata: task-0001 \u2014 Test task",
    result_key: str = "task_id",
    entity_id: int = 1,
) -> ModalTestApp:
    modal = MetadataModal(
        display_title=display_title,
        metadata=metadata if metadata is not None else {},
        result_key=result_key,
        entity_id=entity_id,
    )
    return ModalTestApp(modal)


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

    async def test_header_renders_display_title_verbatim(self):
        app = _make_app(display_title="Metadata: workspace \u2014 Coding")
        async with app.run_test() as pilot:
            modal = app.screen
            header = modal.query_one(".modal-id", Static)
            rendered = str(header.render())
            assert "workspace" in rendered
            assert "Coding" in rendered


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

    async def test_retyping_key_case_only_dismisses_none(self):
        # Stored keys are always lowercase (service normalizes on write).
        # Retyping a key in a different case should be treated as a no-op,
        # not a "changed" dismiss, otherwise the modal triggers a pointless
        # write-and-refresh cycle.
        app = _make_app({"foo": "bar"})
        async with app.run_test() as pilot:
            modal = app.screen
            row = modal.query(".metadata-row").first()
            row.query_one(".metadata-key", Input).value = "FOO"
            modal.action_save()
            await pilot.pause()
            assert app.result is None

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


class TestResultKey:
    """Exercise the dismiss payload for the non-task entity kinds."""

    async def test_workspace_result_key_in_dismiss_payload(self):
        app = _make_app({"env": "prod"}, result_key="workspace_id", entity_id=7)
        async with app.run_test() as pilot:
            modal = app.screen
            row = modal.query(".metadata-row").first()
            row.query_one(".metadata-value", Input).value = "staging"
            modal.action_save()
            await pilot.pause()
            assert app.result == {
                "workspace_id": 7,
                "metadata": {"env": "staging"},
            }

    async def test_project_result_key_in_dismiss_payload(self):
        app = _make_app({}, result_key="project_id", entity_id=42)
        async with app.run_test() as pilot:
            modal = app.screen
            row = modal.query(".metadata-row").first()
            row.query_one(".metadata-key", Input).value = "repo"
            row.query_one(".metadata-value", Input).value = "https://github.com/x/y"
            modal.action_save()
            await pilot.pause()
            assert app.result == {
                "project_id": 42,
                "metadata": {"repo": "https://github.com/x/y"},
            }

    async def test_group_result_key_in_dismiss_payload(self):
        app = _make_app(
            {"owner": "alice"},
            result_key="group_id",
            entity_id=99,
        )
        async with app.run_test() as pilot:
            modal = app.screen
            del_btn = modal.query(".metadata-delete").first()
            modal._on_delete_row(Button.Pressed(del_btn))
            await pilot.pause()
            modal.action_save()
            await pilot.pause()
            assert app.result == {"group_id": 99, "metadata": {}}
