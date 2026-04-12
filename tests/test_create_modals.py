"""Tests for create modals: NewResourceModal, TaskCreateModal, ProjectCreateModal, GroupCreateModal, StatusCreateModal."""

from __future__ import annotations

from helpers import ModalTestApp
from textual.widgets import Input, Select, Static, TextArea

from stx.models import Group, Project, Status, Workspace
from stx.tui.model import GroupNode, ProjectNode
from stx.tui.screens.group_create import GroupCreateModal
from stx.tui.screens.new_resource import NewResourceModal
from stx.tui.screens.project_create import ProjectCreateModal
from stx.tui.screens.status_create import StatusCreateModal
from stx.tui.screens.task_create import TaskCreateModal

# ---- Factories ----


def make_status(**overrides) -> Status:
    defaults = dict(id=1, workspace_id=1, name="todo", archived=False, created_at=0)
    defaults.update(overrides)
    return Status(**defaults)


def make_project(**overrides) -> Project:
    defaults = dict(
        id=1,
        workspace_id=1,
        name="Alpha",
        description=None,
        archived=False,
        created_at=0,
        metadata={},
    )
    defaults.update(overrides)
    return Project(**defaults)


STATUSES = (make_status(id=1, name="todo"), make_status(id=2, name="done"))
PROJECTS = (make_project(id=1, name="Alpha"), make_project(id=2, name="Beta"))

PROJECT_NODES = tuple(ProjectNode(project=p, groups=(), ungrouped_tasks=()) for p in PROJECTS)


def _group(id: int, project_id: int, title: str) -> Group:
    return Group(
        id=id,
        workspace_id=1,
        project_id=project_id,
        title=title,
        description=None,
        parent_id=None,
        position=0,
        archived=False,
        created_at=0,
        metadata={},
    )


def _nodes_with_groups() -> tuple[ProjectNode, ...]:
    alpha_groups = (
        GroupNode(group=_group(10, 1, "Login"), tasks=(), children=()),
        GroupNode(group=_group(11, 1, "Signup"), tasks=(), children=()),
    )
    beta_groups = (GroupNode(group=_group(20, 2, "API"), tasks=(), children=()),)
    return (
        ProjectNode(project=PROJECTS[0], groups=alpha_groups, ungrouped_tasks=()),
        ProjectNode(project=PROJECTS[1], groups=beta_groups, ungrouped_tasks=()),
    )


# ---- NewResourceModal tests ----


class TestNewResourceModal:
    async def test_t_key_dismisses_task(self):
        app = ModalTestApp(NewResourceModal())
        async with app.run_test() as pilot:
            await pilot.press("t")
            assert app.result == "task"

    async def test_g_key_dismisses_group(self):
        app = ModalTestApp(NewResourceModal())
        async with app.run_test() as pilot:
            await pilot.press("g")
            assert app.result == "group"

    async def test_p_key_dismisses_project(self):
        app = ModalTestApp(NewResourceModal())
        async with app.run_test() as pilot:
            await pilot.press("p")
            assert app.result == "project"

    async def test_escape_dismisses_none(self):
        app = ModalTestApp(NewResourceModal())
        async with app.run_test() as pilot:
            await pilot.press("escape")
            assert app.result is None

    async def test_task_button_click(self):
        app = ModalTestApp(NewResourceModal())
        async with app.run_test() as pilot:
            await pilot.click("#new-task")
            assert app.result == "task"

    async def test_group_button_click(self):
        app = ModalTestApp(NewResourceModal())
        async with app.run_test() as pilot:
            await pilot.click("#new-group")
            assert app.result == "group"

    async def test_project_button_click(self):
        app = ModalTestApp(NewResourceModal())
        async with app.run_test() as pilot:
            await pilot.click("#new-project")
            assert app.result == "project"


# ---- TaskCreateModal tests ----


class TestTaskCreateModal:
    async def test_empty_title_shows_error(self):
        app = ModalTestApp(TaskCreateModal(STATUSES, PROJECT_NODES))
        async with app.run_test() as pilot:
            app.screen.action_save()
            await pilot.pause()
            error = app.screen.query_one("#modal-error", Static)
            assert "Title is required" in str(error.render())
            assert app.result == "NOT_SET"

    async def test_cancel_dismisses_none(self):
        app = ModalTestApp(TaskCreateModal(STATUSES, PROJECT_NODES))
        async with app.run_test() as pilot:
            await pilot.press("escape")
            assert app.result is None

    async def test_minimal_task(self):
        app = ModalTestApp(TaskCreateModal(STATUSES, PROJECT_NODES))
        async with app.run_test() as pilot:
            app.screen.query_one("#task-create-title", Input).value = "My task"
            app.screen.action_save()
            await pilot.pause()
            assert app.result == {
                "title": "My task",
                "status_id": 1,
                "priority": 1,
                "project_id": None,
                "group_id": None,
                "description": None,
                "due_date": None,
                "start_date": None,
                "finish_date": None,
            }

    async def test_invalid_date_shows_error(self):
        app = ModalTestApp(TaskCreateModal(STATUSES, PROJECT_NODES))
        async with app.run_test() as pilot:
            app.screen.query_one("#task-create-title", Input).value = "My task"
            app.screen.query_one("#task-create-due", Input).value = "not-a-date"
            app.screen.action_save()
            await pilot.pause()
            error = app.screen.query_one("#modal-error", Static)
            assert "Invalid date" in str(error.render())
            assert app.result == "NOT_SET"

    async def test_finish_before_start_shows_error(self):
        app = ModalTestApp(TaskCreateModal(STATUSES, PROJECT_NODES))
        async with app.run_test() as pilot:
            app.screen.query_one("#task-create-title", Input).value = "My task"
            app.screen.query_one("#task-create-start", Input).value = "2026-06-01"
            app.screen.query_one("#task-create-finish", Input).value = "2026-05-01"
            app.screen.action_save()
            await pilot.pause()
            error = app.screen.query_one("#modal-error", Static)
            assert "Finish date" in str(error.render())
            assert app.result == "NOT_SET"

    async def test_with_description(self):
        app = ModalTestApp(TaskCreateModal(STATUSES, PROJECT_NODES))
        async with app.run_test() as pilot:
            app.screen.query_one("#task-create-title", Input).value = "My task"
            textarea = app.screen.query_one(TextArea)
            textarea.insert("some notes")
            app.screen.action_save()
            await pilot.pause()
            assert app.result["description"] == "some notes"

    async def test_group_select_starts_disabled(self):
        app = ModalTestApp(TaskCreateModal(STATUSES, _nodes_with_groups()))
        async with app.run_test() as pilot:
            group_select = app.screen.query_one("#task-create-group", Select)
            assert group_select.disabled is True

    async def test_selecting_project_enables_group_select(self):
        app = ModalTestApp(TaskCreateModal(STATUSES, _nodes_with_groups()))
        async with app.run_test() as pilot:
            app.screen.query_one("#task-create-project", Select).value = 1
            await pilot.pause()
            group_select = app.screen.query_one("#task-create-group", Select)
            assert group_select.disabled is False

    async def test_create_with_project_and_group(self):
        app = ModalTestApp(TaskCreateModal(STATUSES, _nodes_with_groups()))
        async with app.run_test() as pilot:
            app.screen.query_one("#task-create-title", Input).value = "My task"
            app.screen.query_one("#task-create-project", Select).value = 1
            await pilot.pause()
            app.screen.query_one("#task-create-group", Select).value = 11  # Signup
            app.screen.action_save()
            await pilot.pause()
            assert app.result["project_id"] == 1
            assert app.result["group_id"] == 11

    async def test_changing_project_clears_group(self):
        app = ModalTestApp(TaskCreateModal(STATUSES, _nodes_with_groups()))
        async with app.run_test() as pilot:
            app.screen.query_one("#task-create-project", Select).value = 1
            await pilot.pause()
            app.screen.query_one("#task-create-group", Select).value = 10
            await pilot.pause()
            app.screen.query_one("#task-create-project", Select).value = 2
            await pilot.pause()
            group_select = app.screen.query_one("#task-create-group", Select)
            assert group_select.value is Select.NULL


# ---- ProjectCreateModal tests ----


class TestProjectCreateModal:
    async def test_empty_name_shows_error(self):
        app = ModalTestApp(ProjectCreateModal())
        async with app.run_test() as pilot:
            app.screen.action_save()
            await pilot.pause()
            error = app.screen.query_one("#modal-error", Static)
            assert "Name is required" in str(error.render())
            assert app.result == "NOT_SET"

    async def test_cancel_dismisses_none(self):
        app = ModalTestApp(ProjectCreateModal())
        async with app.run_test() as pilot:
            await pilot.press("escape")
            assert app.result is None

    async def test_name_only(self):
        app = ModalTestApp(ProjectCreateModal())
        async with app.run_test() as pilot:
            app.screen.query_one("#project-create-name", Input).value = "NewProj"
            app.screen.action_save()
            await pilot.pause()
            assert app.result == {"name": "NewProj", "description": None}

    async def test_name_and_description(self):
        app = ModalTestApp(ProjectCreateModal())
        async with app.run_test() as pilot:
            app.screen.query_one("#project-create-name", Input).value = "NewProj"
            textarea = app.screen.query_one(TextArea)
            textarea.insert("A description")
            app.screen.action_save()
            await pilot.pause()
            assert app.result == {"name": "NewProj", "description": "A description"}


# ---- GroupCreateModal tests ----


class TestGroupCreateModal:
    async def test_empty_title_shows_error(self):
        app = ModalTestApp(GroupCreateModal(PROJECTS))
        async with app.run_test() as pilot:
            app.screen.action_save()
            await pilot.pause()
            error = app.screen.query_one("#modal-error", Static)
            assert "Title is required" in str(error.render())
            assert app.result == "NOT_SET"

    async def test_cancel_dismisses_none(self):
        app = ModalTestApp(GroupCreateModal(PROJECTS))
        async with app.run_test() as pilot:
            await pilot.press("escape")
            assert app.result is None

    async def test_valid_group(self):
        app = ModalTestApp(GroupCreateModal(PROJECTS))
        async with app.run_test() as pilot:
            app.screen.query_one("#group-create-title", Input).value = "Sprint 1"
            app.screen.action_save()
            await pilot.pause()
            assert app.result == {"project_id": 1, "title": "Sprint 1", "description": None}


# ---- StatusCreateModal tests ----


def make_workspace(**overrides) -> Workspace:
    defaults = dict(
        id=1,
        name="Main",
        archived=False,
        created_at=0,
        metadata={},
    )
    defaults.update(overrides)
    return Workspace(**defaults)


WORKSPACES = (make_workspace(id=1, name="Main"), make_workspace(id=2, name="Work"))


class TestStatusCreateModal:
    async def test_empty_name_shows_error(self):
        app = ModalTestApp(StatusCreateModal(WORKSPACES, 1))
        async with app.run_test() as pilot:
            app.screen.action_save()
            await pilot.pause()
            error = app.screen.query_one("#modal-error", Static)
            assert "Name is required" in str(error.render())
            assert app.result == "NOT_SET"

    async def test_cancel_dismisses_none(self):
        app = ModalTestApp(StatusCreateModal(WORKSPACES, 1))
        async with app.run_test() as pilot:
            await pilot.press("escape")
            assert app.result is None

    async def test_valid_status(self):
        app = ModalTestApp(StatusCreateModal(WORKSPACES, 1))
        async with app.run_test() as pilot:
            app.screen.query_one("#status-create-name", Input).value = "in-progress"
            app.screen.action_save()
            await pilot.pause()
            assert app.result == {"workspace_id": 1, "name": "in-progress"}

    async def test_default_workspace_selected(self):
        app = ModalTestApp(StatusCreateModal(WORKSPACES, 2))
        async with app.run_test() as pilot:
            sel = app.screen.query_one("#status-create-workspace", Select)
            assert sel.value == 2

    async def test_s_key_dismisses_status(self):
        app = ModalTestApp(NewResourceModal())
        async with app.run_test() as pilot:
            await pilot.press("s")
            assert app.result == "status"

    async def test_status_button_click(self):
        app = ModalTestApp(NewResourceModal())
        async with app.run_test() as pilot:
            await pilot.click("#new-status")
            assert app.result == "status"


# ---- WorkspaceCreateModal tests ----

from stx.tui.screens.workspace_create import WorkspaceCreateModal  # noqa: E402


class TestWorkspaceCreateModal:
    async def test_empty_name_shows_error(self):
        app = ModalTestApp(WorkspaceCreateModal())
        async with app.run_test() as pilot:
            app.screen.action_save()
            await pilot.pause()
            error = app.screen.query_one("#modal-error", Static)
            assert "Name is required" in str(error.render())
            assert app.result == "NOT_SET"

    async def test_cancel_dismisses_none(self):
        app = ModalTestApp(WorkspaceCreateModal())
        async with app.run_test() as pilot:
            await pilot.press("escape")
            assert app.result is None

    async def test_valid_workspace(self):
        app = ModalTestApp(WorkspaceCreateModal())
        async with app.run_test() as pilot:
            app.screen.query_one("#workspace-create-name", Input).value = "My WS"
            app.screen.action_save()
            await pilot.pause()
            assert app.result == {"name": "My WS"}

    async def test_w_key_dismisses_workspace(self):
        app = ModalTestApp(NewResourceModal())
        async with app.run_test() as pilot:
            await pilot.press("w")
            assert app.result == "workspace"

    async def test_workspace_button_click(self):
        app = ModalTestApp(NewResourceModal())
        async with app.run_test() as pilot:
            await pilot.click("#new-workspace")
            assert app.result == "workspace"


# ---- WorkspaceSwitchModal tests ----

from stx.tui.screens.workspace_switch import WorkspaceSwitchModal  # noqa: E402


class TestWorkspaceSwitchModal:
    async def test_switch_button_dismisses_workspace_id(self):
        app = ModalTestApp(WorkspaceSwitchModal(WORKSPACES, current_id=1))
        async with app.run_test() as pilot:
            await pilot.click("#workspace-switch-go")
            assert app.result == 1

    async def test_cancel_dismisses_none(self):
        app = ModalTestApp(WorkspaceSwitchModal(WORKSPACES, current_id=1))
        async with app.run_test() as pilot:
            await pilot.click("#workspace-switch-cancel")
            assert app.result is None

    async def test_escape_dismisses_none(self):
        app = ModalTestApp(WorkspaceSwitchModal(WORKSPACES, current_id=1))
        async with app.run_test() as pilot:
            await pilot.press("escape")
            assert app.result is None

    async def test_default_workspace_selected(self):
        app = ModalTestApp(WorkspaceSwitchModal(WORKSPACES, current_id=2))
        async with app.run_test() as pilot:
            sel = app.screen.query_one("#workspace-switch-select", Select)
            assert sel.value == 2

    async def test_switch_to_second_workspace(self):
        app = ModalTestApp(WorkspaceSwitchModal(WORKSPACES, current_id=1))
        async with app.run_test() as pilot:
            sel = app.screen.query_one("#workspace-switch-select", Select)
            sel.value = 2
            await pilot.click("#workspace-switch-go")
            assert app.result == 2
