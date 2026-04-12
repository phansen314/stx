"""Tests for project, group, and workspace edit modals."""

from __future__ import annotations

from helpers import ModalTestApp
from textual.widgets import Input, Static, TextArea

from sticky_notes.models import Workspace
from sticky_notes.service_models import GroupDetail, ProjectDetail
from sticky_notes.tui.screens.group_edit import GroupEditModal
from sticky_notes.tui.screens.project_create import ProjectCreateModal
from sticky_notes.tui.screens.project_edit import ProjectEditModal
from sticky_notes.tui.screens.workspace_create import WorkspaceCreateModal
from sticky_notes.tui.screens.workspace_edit import WorkspaceEditModal

# ---- Factories ----


def make_project_detail(**overrides) -> ProjectDetail:
    defaults = dict(
        id=1,
        workspace_id=1,
        name="Alpha",
        description="A project",
        archived=False,
        created_at=0,
        tasks=(),
        metadata={},
    )
    defaults.update(overrides)
    return ProjectDetail(**defaults)


def make_group_detail(**overrides) -> GroupDetail:
    defaults = dict(
        id=1,
        workspace_id=1,
        project_id=1,
        title="Sprint 1",
        description=None,
        parent_id=None,
        position=0,
        archived=False,
        created_at=0,
        tasks=(),
        children=(),
        parent=None,
        metadata={},
    )
    defaults.update(overrides)
    return GroupDetail(**defaults)


def make_workspace(**overrides) -> Workspace:
    defaults = dict(
        id=1,
        name="Dev",
        archived=False,
        created_at=0,
        metadata={},
    )
    defaults.update(overrides)
    return Workspace(**defaults)


# ---- Project edit modal tests ----


class TestProjectEditModal:
    async def test_no_changes_dismisses_none(self):
        app = ModalTestApp(ProjectEditModal(make_project_detail()))
        async with app.run_test() as pilot:
            app.screen.action_save()
            await pilot.pause()
            assert app.result is None

    async def test_cancel_dismisses_none(self):
        app = ModalTestApp(ProjectEditModal(make_project_detail()))
        async with app.run_test() as pilot:
            await pilot.press("escape")
            assert app.result is None

    async def test_empty_name_shows_error(self):
        app = ModalTestApp(ProjectEditModal(make_project_detail()))
        async with app.run_test() as pilot:
            modal = app.screen
            modal.query_one("#project-edit-name", Input).value = ""
            modal.action_save()
            await pilot.pause()
            error = modal.query_one("#modal-error", Static)
            assert "Name is required" in str(error.render())
            assert app.result == "NOT_SET"

    async def test_name_change(self):
        app = ModalTestApp(ProjectEditModal(make_project_detail()))
        async with app.run_test() as pilot:
            modal = app.screen
            modal.query_one("#project-edit-name", Input).value = "Beta"
            modal.action_save()
            await pilot.pause()
            assert app.result == {"project_id": 1, "changes": {"name": "Beta"}}

    async def test_description_change(self):
        app = ModalTestApp(ProjectEditModal(make_project_detail()))
        async with app.run_test() as pilot:
            modal = app.screen
            textarea = modal.query_one(TextArea)
            textarea.clear()
            textarea.insert("new desc")
            modal.action_save()
            await pilot.pause()
            assert app.result == {"project_id": 1, "changes": {"description": "new desc"}}

    async def test_empty_description_becomes_none(self):
        app = ModalTestApp(ProjectEditModal(make_project_detail(description="something")))
        async with app.run_test() as pilot:
            modal = app.screen
            textarea = modal.query_one(TextArea)
            textarea.clear()
            modal.action_save()
            await pilot.pause()
            assert app.result == {"project_id": 1, "changes": {"description": None}}

    async def test_multiple_changes(self):
        app = ModalTestApp(ProjectEditModal(make_project_detail()))
        async with app.run_test() as pilot:
            modal = app.screen
            modal.query_one("#project-edit-name", Input).value = "Beta"
            textarea = modal.query_one(TextArea)
            textarea.clear()
            textarea.insert("updated")
            modal.action_save()
            await pilot.pause()
            assert app.result == {
                "project_id": 1,
                "changes": {"name": "Beta", "description": "updated"},
            }


# ---- Group edit modal tests ----


class TestGroupEditModal:
    async def test_no_changes_dismisses_none(self):
        app = ModalTestApp(GroupEditModal(make_group_detail()))
        async with app.run_test() as pilot:
            app.screen.action_save()
            await pilot.pause()
            assert app.result is None

    async def test_cancel_dismisses_none(self):
        app = ModalTestApp(GroupEditModal(make_group_detail()))
        async with app.run_test() as pilot:
            await pilot.press("escape")
            assert app.result is None

    async def test_empty_title_shows_error(self):
        app = ModalTestApp(GroupEditModal(make_group_detail()))
        async with app.run_test() as pilot:
            modal = app.screen
            modal.query_one("#group-edit-title", Input).value = ""
            modal.action_save()
            await pilot.pause()
            error = modal.query_one("#modal-error", Static)
            assert "Title is required" in str(error.render())
            assert app.result == "NOT_SET"

    async def test_title_change(self):
        app = ModalTestApp(GroupEditModal(make_group_detail()))
        async with app.run_test() as pilot:
            modal = app.screen
            modal.query_one("#group-edit-title", Input).value = "Sprint 2"
            modal.action_save()
            await pilot.pause()
            assert app.result == {"group_id": 1, "changes": {"title": "Sprint 2"}}


# ---- Workspace edit modal tests ----


class TestWorkspaceEditModal:
    async def test_no_changes_dismisses_none(self):
        app = ModalTestApp(WorkspaceEditModal(make_workspace()))
        async with app.run_test() as pilot:
            app.screen.action_save()
            await pilot.pause()
            assert app.result is None

    async def test_cancel_dismisses_none(self):
        app = ModalTestApp(WorkspaceEditModal(make_workspace()))
        async with app.run_test() as pilot:
            await pilot.press("escape")
            assert app.result is None

    async def test_empty_name_shows_error(self):
        app = ModalTestApp(WorkspaceEditModal(make_workspace()))
        async with app.run_test() as pilot:
            modal = app.screen
            modal.query_one("#workspace-edit-name", Input).value = ""
            modal.action_save()
            await pilot.pause()
            error = modal.query_one("#modal-error", Static)
            assert "Name is required" in str(error.render())
            assert app.result == "NOT_SET"

    async def test_name_change(self):
        app = ModalTestApp(WorkspaceEditModal(make_workspace()))
        async with app.run_test() as pilot:
            modal = app.screen
            modal.query_one("#workspace-edit-name", Input).value = "Production"
            modal.action_save()
            await pilot.pause()
            assert app.result == {"workspace_id": 1, "changes": {"name": "Production"}}


# ---- BaseEditModal keyboard binding tests ----


class TestBaseEditKeyBindings:
    """Tests for shared BaseEditModal key bindings and button handlers."""

    async def test_ctrl_n_does_not_crash(self):
        """ctrl+n calls focus_next — just verify no exception."""
        app = ModalTestApp(WorkspaceCreateModal())
        async with app.run_test() as pilot:
            await pilot.press("ctrl+n")

    async def test_ctrl_b_does_not_crash(self):
        """ctrl+b calls focus_previous — just verify no exception."""
        app = ModalTestApp(WorkspaceCreateModal())
        async with app.run_test() as pilot:
            await pilot.press("ctrl+b")

    async def test_save_button_click_triggers_validation(self):
        """Clicking #modal-save on empty form shows error (goes through on_button_pressed → action_save)."""
        app = ModalTestApp(WorkspaceCreateModal())
        async with app.run_test() as pilot:
            await pilot.click("#modal-save")
            await pilot.pause()
            error = app.screen.query_one("#modal-error", Static)
            assert "Name is required" in str(error.render())

    async def test_cancel_button_click_dismisses_none(self):
        """Clicking #modal-cancel goes through on_button_pressed → dismiss(None)."""
        app = ModalTestApp(WorkspaceCreateModal())
        async with app.run_test() as pilot:
            await pilot.click("#modal-cancel")
            assert app.result is None

    async def test_editor_mode_no_markdown_editor(self):
        """ctrl+e on modal without MarkdownEditor hits NoMatches → silent pass."""
        app = ModalTestApp(WorkspaceCreateModal())
        async with app.run_test() as pilot:
            await pilot.press("ctrl+e")

    async def test_preview_mode_no_markdown_editor(self):
        """ctrl+r on modal without MarkdownEditor hits NoMatches → silent pass."""
        app = ModalTestApp(WorkspaceCreateModal())
        async with app.run_test() as pilot:
            await pilot.press("ctrl+r")

    async def test_editor_mode_with_markdown_editor(self):
        """ctrl+e on modal with MarkdownEditor calls switch_to_editor()."""
        app = ModalTestApp(ProjectCreateModal())
        async with app.run_test() as pilot:
            await pilot.press("ctrl+e")

    async def test_preview_mode_with_markdown_editor(self):
        """ctrl+r on modal with MarkdownEditor calls switch_to_preview()."""
        app = ModalTestApp(ProjectCreateModal())
        async with app.run_test() as pilot:
            await pilot.press("ctrl+r")
