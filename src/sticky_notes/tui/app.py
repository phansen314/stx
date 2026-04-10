from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import replace
from enum import StrEnum
from pathlib import Path

from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, Horizontal
from textual.message import Message
from textual.widgets import Header, Footer

from sticky_notes.active_workspace import get_active_workspace_id
from sticky_notes.connection import DEFAULT_DB_PATH, get_connection, init_db
from sticky_notes.models import Group, Project, Status, Task, Workspace
from sticky_notes.service import create_group, create_project, create_task, get_group_detail, get_project_detail, get_task_detail, get_workspace, list_workspaces, replace_task_metadata, update_group, update_project, update_task, update_workspace
from sticky_notes.tui.config import TuiConfig, load_config
from sticky_notes.tui.model import WorkspaceModel, load_workspace_model
from sticky_notes.tui.screens import GroupCreateModal, GroupEditModal, NewResourceModal, ProjectCreateModal, ProjectEditModal, TaskCreateModal, TaskEditModal, TaskMetadataModal, WorkspaceEditModal
from sticky_notes.tui.widgets import KanbanBoard, TaskCard, WorkspaceTree


class ActivePanel(StrEnum):
    TREE = "tree"
    KANBAN = "kanban"


class _RefreshRequested(Message):
    """Coalescing refresh message — duplicates in the queue merge into one."""

    def can_replace(self, message: Message) -> bool:
        return isinstance(message, _RefreshRequested)


class StickyNotesApp(App):
    CSS_PATH = "sticky_notes.tcss"
    TITLE = "\U0001f4cc Sticky Notes \U0001f4cc"
    BINDINGS = [
        Binding("w", "focus_tree", "Workspace", show=True),
        Binding("b", "focus_kanban", "Board", show=True),
        Binding("r", "refresh", "Refresh", show=True),
        Binding("e", "edit", "Edit", show=True),
        Binding("m", "metadata", "Meta", show=True),
        Binding("[", "status_left", "◀ Status", show=False),
        Binding("shift+left", "status_left", show=False),
        Binding("]", "status_right", "Status ▶", show=False),
        Binding("shift+right", "status_right", show=False),
        Binding("n", "new", "New", show=True),
        Binding("ctrl+q", "quit", "Quit", show=True),
    ]

    conn: sqlite3.Connection
    config: TuiConfig
    active_panel: ActivePanel = ActivePanel.TREE
    _kanban_last_focused: TaskCard | None = None
    _active_workspace_id: int | None = None
    _models: dict[int, WorkspaceModel]

    @property
    def _active_model(self) -> WorkspaceModel | None:
        if self._active_workspace_id is None:
            return None
        return self._models.get(self._active_workspace_id)

    def __init__(self, db_path: Path | None = None, config: TuiConfig | None = None):
        super().__init__()
        self.db_path = db_path or DEFAULT_DB_PATH
        self.conn = get_connection(self.db_path)
        init_db(self.conn)
        self.config = config or load_config()
        self._models = {}

    def compose(self) -> ComposeResult:
        yield Header()

        with Horizontal(id="main-panels"):
            with Vertical(id="workspaces-panel"):
                yield WorkspaceTree("Root", id="workspaces-tree")
            with Vertical(id="kanban-panel"):
                yield KanbanBoard(id="kanban-columns")
        yield Footer()

    async def on_mount(self) -> None:
        tree = self.query_one(WorkspaceTree)
        kanban = self.query_one(KanbanBoard)
        workspaces = list_workspaces(self.conn)
        if not workspaces:
            tree.show_empty("No workspaces")
            return
        for ws in workspaces:
            try:
                model = load_workspace_model(self.conn, ws.id)
            except LookupError:
                continue
            model = replace(model, statuses=self._order_statuses(model.statuses, ws.id))
            self._models[ws.id] = model
        if not self._models:
            tree.show_empty("No workspaces")
            return
        # Use active-workspace file as initial-focus hint
        hint_id = get_active_workspace_id(self.db_path)
        if hint_id not in self._models:
            hint_id = workspaces[0].id
        self._active_workspace_id = hint_id
        tree.load(self._models, expand_workspace_id=hint_id)
        await kanban.load(self._models[hint_id])
        tree.focus()
        self.set_interval(self.config.auto_refresh_seconds, self.request_refresh)

    def request_refresh(self) -> None:
        self.post_message(_RefreshRequested())

    def action_refresh(self) -> None:
        self.request_refresh()

    async def on__refresh_requested(self, event: _RefreshRequested) -> None:
        # Skip auto-refresh while a modal is open to avoid stealing focus
        if len(self.screen_stack) > 1:
            return

        tree = self.query_one(WorkspaceTree)
        kanban = self.query_one(KanbanBoard)

        self._reconcile_workspaces()

        if not self._models:
            self._active_workspace_id = None
            tree.show_empty("No workspaces")
            await kanban.remove_children()
            return

        if self._active_workspace_id not in self._models:
            self._active_workspace_id = next(iter(self._models))

        model = self._reload_active_model()
        if model is None:
            return

        await self._rerender(tree, kanban, model)

    def _reconcile_workspaces(self) -> None:
        """Sync self._models with the live workspace list — add new, drop archived."""
        live_ids = {ws.id for ws in list_workspaces(self.conn)}
        for stale_id in set(self._models) - live_ids:
            del self._models[stale_id]
        for ws_id in live_ids - set(self._models):
            try:
                model = load_workspace_model(self.conn, ws_id)
                model = replace(model, statuses=self._order_statuses(model.statuses, ws_id))
                self._models[ws_id] = model
            except LookupError:
                continue

    def _reload_active_model(self) -> WorkspaceModel | None:
        """Reload the active workspace from disk. Returns None if it's gone."""
        try:
            model = load_workspace_model(self.conn, self._active_workspace_id)
        except LookupError:
            return None
        model = replace(model, statuses=self._order_statuses(model.statuses, self._active_workspace_id))
        self._models[self._active_workspace_id] = model
        return model

    async def _rerender(self, tree: WorkspaceTree, kanban: KanbanBoard, model: WorkspaceModel) -> None:
        """Redraw the tree + kanban and restore focus to the previously focused card if possible."""
        prev_task_id: int | None = None
        if self._kanban_last_focused is not None:
            prev_task_id = self._kanban_last_focused.task_data.id
        tree.load(self._models, expand_workspace_id=self._active_workspace_id)
        await kanban.sync(model)
        if self.active_panel == ActivePanel.KANBAN and prev_task_id is not None:
            for card in self.query(TaskCard):
                if card.task_data.id == prev_task_id:
                    self._kanban_last_focused = card
                    self.set_focus(card)
                    return
            # Task no longer exists — focus first card or fall back to tree
            cards = self.query(TaskCard)
            if cards:
                self._kanban_last_focused = cards.first()
                self.set_focus(cards.first())
            else:
                self.set_focus(tree)
        else:
            self.set_focus(tree)

    def on_descendant_focus(self, event: events.DescendantFocus) -> None:
        widget = event.widget
        if isinstance(widget, WorkspaceTree):
            self.active_panel = ActivePanel.TREE
        elif isinstance(widget, TaskCard):
            self.active_panel = ActivePanel.KANBAN
            self._kanban_last_focused = widget

    def action_status_left(self) -> None:
        self.query_one(KanbanBoard)._move_status(-1)

    def action_status_right(self) -> None:
        self.query_one(KanbanBoard)._move_status(1)

    def action_focus_tree(self) -> None:
        self.set_focus(self.query_one(WorkspaceTree))

    def action_focus_kanban(self) -> None:
        if self._kanban_last_focused is not None and self._kanban_last_focused.parent is not None:
            self.set_focus(self._kanban_last_focused)
        else:
            cards = self.query("TaskCard")
            if cards:
                self.set_focus(cards.first())

    async def on_workspace_tree_workspace_changed(self, event: WorkspaceTree.WorkspaceChanged) -> None:
        ws_id = event.workspace_id
        if ws_id == self._active_workspace_id:
            return
        self._active_workspace_id = ws_id
        try:
            model = load_workspace_model(self.conn, ws_id)
        except LookupError:
            return
        model = replace(model, statuses=self._order_statuses(model.statuses, ws_id))
        self._models[ws_id] = model
        tree = self.query_one(WorkspaceTree)
        kanban = self.query_one(KanbanBoard)
        tree.load(self._models, expand_workspace_id=ws_id)
        await kanban.load(model)
        self._kanban_last_focused = None

    def action_edit(self) -> None:
        if self._active_model is None:
            return
        if self.active_panel == ActivePanel.TREE:
            tree = self.query_one(WorkspaceTree)
            node = tree.cursor_node
            if node is not None:
                if isinstance(node.data, Task):
                    self._edit_task(node.data)
                elif isinstance(node.data, Project):
                    self._edit_project(node.data)
                elif isinstance(node.data, Group):
                    self._edit_group(node.data)
                elif isinstance(node.data, Workspace):
                    self._edit_workspace(node.data)
        elif self._kanban_last_focused is not None:
            self._edit_task(self._kanban_last_focused.task_data)

    def _dismiss_callback(self, result: dict | None, save: Callable[[], None]) -> None:
        if result is None:
            return
        try:
            save()
        except ValueError as e:
            self.notify(str(e), severity="error")
            return
        self.request_refresh()

    def _edit_task(self, task: Task) -> None:
        detail = get_task_detail(self.conn, task.id)
        model = self._models[task.workspace_id]
        self.push_screen(
            TaskEditModal(detail, model.statuses, model.projects),
            callback=self._on_task_edit_dismiss,
        )

    def _on_task_edit_dismiss(self, result: dict | None) -> None:
        self._dismiss_callback(result, lambda: update_task(self.conn, result["task_id"], result["changes"], source="tui"))

    def action_metadata(self) -> None:
        if self._active_model is None:
            return
        task: Task | None = None
        if self.active_panel == ActivePanel.TREE:
            node = self.query_one(WorkspaceTree).cursor_node
            if node is not None and isinstance(node.data, Task):
                task = node.data
        elif self._kanban_last_focused is not None:
            task = self._kanban_last_focused.task_data
        if task is None:
            return
        detail = get_task_detail(self.conn, task.id)
        self.push_screen(
            TaskMetadataModal(detail),
            callback=self._on_task_metadata_dismiss,
        )

    def _on_task_metadata_dismiss(self, result: dict | None) -> None:
        self._dismiss_callback(
            result,
            lambda: replace_task_metadata(
                self.conn, result["task_id"], result["metadata"], source="tui",
            ),
        )

    def _edit_project(self, project: Project) -> None:
        detail = get_project_detail(self.conn, project.id)
        self.push_screen(
            ProjectEditModal(detail),
            callback=self._on_project_edit_dismiss,
        )

    def _on_project_edit_dismiss(self, result: dict | None) -> None:
        self._dismiss_callback(result, lambda: update_project(self.conn, result["project_id"], result["changes"]))

    def _edit_group(self, group: Group) -> None:
        detail = get_group_detail(self.conn, group.id)
        self.push_screen(
            GroupEditModal(detail),
            callback=self._on_group_edit_dismiss,
        )

    def _on_group_edit_dismiss(self, result: dict | None) -> None:
        self._dismiss_callback(result, lambda: update_group(self.conn, result["group_id"], result["changes"]))

    def _edit_workspace(self, workspace: Workspace) -> None:
        fresh = get_workspace(self.conn, workspace.id)
        self.push_screen(
            WorkspaceEditModal(fresh),
            callback=self._on_workspace_edit_dismiss,
        )

    def _on_workspace_edit_dismiss(self, result: dict | None) -> None:
        self._dismiss_callback(result, lambda: update_workspace(self.conn, result["workspace_id"], result["changes"]))

    async def on_kanban_board_task_status_move(self, event: KanbanBoard.TaskStatusMove) -> None:
        try:
            update_task(self.conn, event.task.id, {"status_id": event.new_status_id}, source="tui")
        except ValueError as e:
            self.notify(str(e), severity="error")
            return
        self.request_refresh()

    def action_new(self) -> None:
        if self._active_model is None:
            return
        self.push_screen(NewResourceModal(), callback=self._on_new_resource)

    def _on_new_resource(self, resource_type: str | None) -> None:
        dispatch = {
            "task": self._create_task,
            "group": self._create_group,
            "project": self._create_project,
        }
        action = dispatch.get(resource_type)
        if action is not None:
            action()

    def _create_task(self) -> None:
        statuses = self._active_model.statuses
        if not statuses:
            self.notify("No statuses — create one first", severity="warning")
            return
        self.push_screen(
            TaskCreateModal(statuses, self._active_model.projects),
            callback=self._on_task_create_dismiss,
        )

    def _on_task_create_dismiss(self, result: dict | None) -> None:
        self._dismiss_callback(result, lambda: create_task(self.conn, self._active_workspace_id, **result))

    def _create_project(self) -> None:
        self.push_screen(
            ProjectCreateModal(),
            callback=self._on_project_create_dismiss,
        )

    def _on_project_create_dismiss(self, result: dict | None) -> None:
        self._dismiss_callback(result, lambda: create_project(self.conn, self._active_workspace_id, **result))

    def _create_group(self) -> None:
        projects = tuple(p.project for p in self._active_model.projects)
        if not projects:
            self.notify("No projects — create one first", severity="warning")
            return
        self.push_screen(
            GroupCreateModal(projects),
            callback=self._on_group_create_dismiss,
        )

    def _on_group_create_dismiss(self, result: dict | None) -> None:
        self._dismiss_callback(result, lambda: create_group(self.conn, **result))

    def _order_statuses(self, statuses: tuple[Status, ...], workspace_id: int) -> tuple[Status, ...]:
        order = self.config.status_order.get(workspace_id, [])
        if not order:
            return statuses
        order_map = {sid: i for i, sid in enumerate(order)}
        return tuple(sorted(statuses, key=lambda s: (order_map.get(s.id, len(order)), s.id)))
