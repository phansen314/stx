from __future__ import annotations

import sqlite3
from enum import StrEnum
from pathlib import Path

from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, Horizontal
from textual.widgets import Header, Footer

from sticky_notes.active_workspace import get_active_workspace_id
from sticky_notes.connection import DEFAULT_DB_PATH, get_connection, init_db
from sticky_notes.models import Task
from sticky_notes.service import get_task_detail, update_task
from sticky_notes.tui.config import TuiConfig, load_config
from sticky_notes.tui.model import WorkspaceModel, load_workspace_model
from sticky_notes.tui.screens import TaskEditModal
from sticky_notes.tui.widgets import KanbanBoard, TaskCard, WorkspaceTree


class ActivePanel(StrEnum):
    TREE = "tree"
    KANBAN = "kanban"


class StickyNotesApp(App):
    CSS_PATH = "sticky_notes.tcss"
    TITLE = "\U0001f4cc Sticky Notes \U0001f4cc"
    BINDINGS = [
        Binding("w", "focus_tree", "Workspace", show=True),
        Binding("k", "focus_kanban", "Kanban", show=True),
        Binding("r", "refresh", "Refresh", show=True),
        Binding("e", "edit_task", "Edit", show=True),
        Binding("ctrl+q", "quit", "Quit", show=True),
    ]

    conn: sqlite3.Connection
    config: TuiConfig
    active_panel: ActivePanel = ActivePanel.TREE
    _kanban_last_focused: TaskCard | None = None
    _workspace_id: int | None = None
    _model: WorkspaceModel | None = None

    def __init__(self, db_path: Path | None = None):
        super().__init__()
        self.db_path = db_path or DEFAULT_DB_PATH
        self.conn = get_connection(self.db_path)
        init_db(self.conn)
        self.config = load_config()

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
        self._workspace_id = get_active_workspace_id(self.db_path)
        if self._workspace_id is None:
            tree.show_empty("No active workspace")
            return
        try:
            model = load_workspace_model(self.conn, self._workspace_id)
        except LookupError:
            tree.show_empty("Workspace not found")
            return
        self._model = model
        tree.load(model)
        await kanban.load(model)
        tree.focus()
        self.set_interval(self.config.auto_refresh_seconds, self._refresh)

    async def action_refresh(self) -> None:
        await self._refresh()

    async def _refresh(self) -> None:
        if self._workspace_id is None:
            return
        try:
            model = load_workspace_model(self.conn, self._workspace_id)
        except LookupError:
            return
        tree = self.query_one(WorkspaceTree)
        kanban = self.query_one(KanbanBoard)
        # Remember focused task id before reload
        prev_task_id: int | None = None
        if self._kanban_last_focused is not None:
            prev_task_id = self._kanban_last_focused.task_data.id
        self._model = model
        tree.load(model)
        await kanban.load(model)
        # Restore focus
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

    def action_focus_tree(self) -> None:
        self.set_focus(self.query_one(WorkspaceTree))

    def action_focus_kanban(self) -> None:
        if self._kanban_last_focused is not None and self._kanban_last_focused.parent is not None:
            self.set_focus(self._kanban_last_focused)
        else:
            cards = self.query("TaskCard")
            if cards:
                self.set_focus(cards.first())

    def action_edit_task(self) -> None:
        task = self._get_focused_task()
        if task is None or self._model is None:
            return
        detail = get_task_detail(self.conn, task.id)
        statuses = self._model.statuses
        projects = tuple(p.project for p in self._model.projects)
        self.push_screen(
            TaskEditModal(detail, statuses, projects),
            callback=self._on_edit_dismiss,
        )

    async def _on_edit_dismiss(self, result: dict | None) -> None:
        if result is None:
            return
        update_task(self.conn, result["task_id"], result["changes"], source="tui")
        await self._refresh()

    def _get_focused_task(self) -> Task | None:
        if self.active_panel == ActivePanel.TREE:
            tree = self.query_one(WorkspaceTree)
            node = tree.cursor_node
            if node is not None and isinstance(node.data, Task):
                return node.data
        elif self._kanban_last_focused is not None:
            return self._kanban_last_focused.task_data
        return None

