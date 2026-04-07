from __future__ import annotations

import sqlite3
from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import Vertical, Horizontal
from textual.widgets import Header, Footer

from sticky_notes.active_workspace import get_active_workspace_id
from sticky_notes.connection import DEFAULT_DB_PATH, get_connection, init_db
from sticky_notes.tui.config import TuiConfig, load_config
from sticky_notes.tui.model import load_workspace_model
from sticky_notes.tui.widgets import KanbanBoard, WorkspaceTree


class StickyNotesApp(App):
    CSS_PATH = "sticky_notes.tcss"
    TITLE = "Sticky Notes"

    conn: sqlite3.Connection
    config: TuiConfig

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

    def on_mount(self) -> None:
        tree = self.query_one(WorkspaceTree)
        kanban = self.query_one(KanbanBoard)
        ws_id = get_active_workspace_id(self.db_path)
        if ws_id is None:
            tree.show_empty("No active workspace")
            return
        try:
            model = load_workspace_model(self.conn, ws_id)
        except LookupError:
            tree.show_empty("Workspace not found")
            return
        tree.load(model)
        kanban.load(model)
