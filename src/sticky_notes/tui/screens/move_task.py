from __future__ import annotations

import sqlite3

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Select, Static

from sticky_notes import service
from sticky_notes.models import Board, Project, Status


class MoveTaskModal(ModalScreen[dict | None]):
    DEFAULT_CSS = """
    MoveTaskModal {
        align: center middle;
    }

    MoveTaskModal #move-container {
        width: 70%;
        max-height: 60%;
        padding: 1 2;
        border: thick $primary;
        background: $surface;
    }

    MoveTaskModal #move-title {
        text-style: bold;
        text-align: center;
        margin-bottom: 1;
    }

    MoveTaskModal .form-field {
        margin-bottom: 1;
    }

    MoveTaskModal .form-label {
        margin-bottom: 0;
    }

    MoveTaskModal #move-buttons {
        width: 100%;
        align: center middle;
        height: 3;
        margin-top: 1;
    }

    MoveTaskModal #move-buttons Button {
        margin: 0 1;
    }

    MoveTaskModal #move-error {
        color: $error;
        text-align: center;
        margin-top: 1;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False),
        Binding("ctrl+s", "submit", "Move"),
    ]

    def __init__(
        self,
        conn: sqlite3.Connection,
        current_board_id: int,
        task_id: int,
    ) -> None:
        super().__init__()
        self._conn = conn
        self._current_board_id = current_board_id
        self._task_id = task_id
        self._boards: tuple[Board, ...] = service.list_boards(conn)
        self._statuses: tuple[Status, ...] = service.list_statuses(conn, current_board_id)
        self._projects: tuple[Project, ...] = service.list_projects(conn, current_board_id)

    def compose(self) -> ComposeResult:
        board_options = [(b.name, b.id) for b in self._boards]
        status_options = [(s.name, s.id) for s in self._statuses]
        project_options = [(p.name, p.id) for p in self._projects]

        with VerticalScroll(id="move-container"):
            yield Static("Move Task to Board", id="move-title")

            yield Static("Board", classes="form-label")
            yield Select(
                board_options,
                value=self._current_board_id,
                id="move-select-board",
                allow_blank=False,
                classes="form-field",
            )

            yield Static("Status", classes="form-label")
            yield Select(
                status_options,
                value=self._statuses[0].id if self._statuses else Select.BLANK,
                id="move-select-status",
                allow_blank=False,
                classes="form-field",
            )

            yield Static("Project", classes="form-label")
            yield Select(
                project_options,
                id="move-select-project",
                allow_blank=True,
                classes="form-field",
            )

            yield Static("", id="move-error")
            with Horizontal(id="move-buttons"):
                yield Button("Move", variant="primary", id="move-submit")
                yield Button("Cancel", id="move-cancel")

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id != "move-select-board":
            return
        new_board_id = event.value
        if not isinstance(new_board_id, int):
            return

        new_statuses = service.list_statuses(self._conn, new_board_id)
        status_select = self.query_one("#move-select-status", Select)
        status_select.set_options([(s.name, s.id) for s in new_statuses])
        if new_statuses:
            status_select.value = new_statuses[0].id

        new_projects = service.list_projects(self._conn, new_board_id)
        proj_select = self.query_one("#move-select-project", Select)
        proj_select.set_options([(p.name, p.id) for p in new_projects])
        proj_select.clear()

        self.query_one("#move-error", Static).update("")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "move-submit":
            self._submit()
        else:
            self.dismiss(None)

    def _submit(self) -> None:
        board_select = self.query_one("#move-select-board", Select)
        selected_board = board_select.value
        if not isinstance(selected_board, int):
            self.query_one("#move-error", Static).update("Select a board")
            return

        if selected_board == self._current_board_id:
            self.query_one("#move-error", Static).update("Task is already on this board")
            return

        status_select = self.query_one("#move-select-status", Select)
        selected_status = status_select.value
        if not isinstance(selected_status, int):
            self.query_one("#move-error", Static).update("Select a status")
            return

        proj_select = self.query_one("#move-select-project", Select)
        project_id = proj_select.value if isinstance(proj_select.value, int) else None

        self.dismiss({
            "target_board_id": selected_board,
            "target_status_id": selected_status,
            "project_id": project_id,
        })

    def action_submit(self) -> None:
        self._submit()

    def action_cancel(self) -> None:
        self.dismiss(None)
