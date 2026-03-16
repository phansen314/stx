from __future__ import annotations

import sqlite3
from typing import Literal

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.validation import Function
from textual.widgets import Button, Input, Select, Static, TextArea

from sticky_notes import service
from sticky_notes.formatting import format_timestamp, parse_date
from sticky_notes.models import Column, Project


def _validate_date(value: str) -> bool:
    if not value:
        return True
    try:
        parse_date(value)
        return True
    except ValueError:
        return False


class TaskFormModal(ModalScreen[dict | None]):
    DEFAULT_CSS = """
    TaskFormModal {
        align: center middle;
    }

    TaskFormModal #form-container {
        width: 90%;
        max-height: 85%;
        padding: 1 2;
        border: thick $primary;
        background: $surface;
    }

    TaskFormModal #form-title {
        text-style: bold;
        text-align: center;
        margin-bottom: 1;
    }

    TaskFormModal .form-field {
        margin-bottom: 1;
    }

    TaskFormModal .form-label {
        margin-bottom: 0;
    }

    TaskFormModal #form-buttons {
        width: 100%;
        align: center middle;
        height: 3;
        margin-top: 1;
    }

    TaskFormModal #form-buttons Button {
        margin: 0 1;
    }

    TaskFormModal #form-error {
        color: $error;
        text-align: center;
        margin-top: 1;
    }

    TaskFormModal TextArea {
        height: 5;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False),
        Binding("ctrl+s", "submit", "Submit"),
    ]

    def __init__(
        self,
        conn: sqlite3.Connection,
        board_id: int,
        *,
        mode: Literal["create", "edit"] = "create",
        column_id: int | None = None,
        defaults: dict | None = None,
        default_priority: int = 1,
    ) -> None:
        super().__init__()
        self._mode = mode
        self._column_id = column_id
        self._defaults = defaults or {}
        self._default_priority = default_priority
        self._columns: tuple[Column, ...] = service.list_columns(conn, board_id)
        self._projects: tuple[Project, ...] = service.list_projects(conn, board_id)

    def compose(self) -> ComposeResult:
        title_text = "New Task" if self._mode == "create" else "Edit Task"

        with VerticalScroll(id="form-container"):
            yield Static(title_text, id="form-title")

            yield Static("Title", classes="form-label")
            yield Input(
                value=self._defaults.get("title", ""),
                placeholder="Task title (required)",
                id="form-input-title",
                classes="form-field",
            )

            yield Static("Description", classes="form-label")
            yield TextArea(
                self._defaults.get("description", "") or "",
                id="form-input-desc",
                classes="form-field",
            )

            yield Static("Priority", classes="form-label")
            yield Select(
                [(str(i), i) for i in range(1, 6)],
                value=self._defaults.get("priority", self._default_priority),
                id="form-select-priority",
                allow_blank=False,
                classes="form-field",
            )

            yield Static("Due Date", classes="form-label")
            default_due = ""
            if self._defaults.get("due_date"):
                default_due = format_timestamp(self._defaults["due_date"])
            yield Input(
                value=default_due,
                placeholder="YYYY-MM-DD (optional)",
                id="form-input-due",
                validators=[Function(_validate_date, "Invalid date format (expected YYYY-MM-DD)")],
                classes="form-field",
            )

            project_options = [(p.name, p.id) for p in self._projects]
            yield Static("Project", classes="form-label")
            yield Select(
                project_options,
                id="form-select-project",
                allow_blank=True,
                classes="form-field",
            )

            if self._mode == "create":
                column_options = [(c.name, c.id) for c in self._columns]
                default_col = self._column_id if self._column_id is not None else (
                    self._columns[0].id if self._columns else Select.BLANK
                )
                yield Static("Column", classes="form-label")
                yield Select(
                    column_options,
                    value=default_col,
                    id="form-select-column",
                    allow_blank=False,
                    classes="form-field",
                )

            yield Static("", id="form-error")
            with Horizontal(id="form-buttons"):
                submit_label = "Create" if self._mode == "create" else "Save"
                yield Button(submit_label, variant="primary", id="form-submit")
                yield Button("Cancel", id="form-cancel")

    def on_mount(self) -> None:
        default_project = self._defaults.get("project_id")
        if default_project is not None:
            self.query_one("#form-select-project", Select).value = default_project
        self.query_one("#form-input-title", Input).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "form-submit":
            self._submit()
        else:
            self.dismiss(None)

    def _submit(self) -> None:
        title = self.query_one("#form-input-title", Input).value.strip()
        if not title:
            self.query_one("#form-error", Static).update("Title is required")
            return

        due_input = self.query_one("#form-input-due", Input)
        due_raw = due_input.value.strip()
        due_date = None
        if due_raw:
            try:
                due_date = parse_date(due_raw)
            except ValueError:
                self.query_one("#form-error", Static).update("Invalid date format (expected YYYY-MM-DD)")
                return

        desc_area = self.query_one("#form-input-desc", TextArea)
        description = desc_area.text.strip() or None

        priority_select = self.query_one("#form-select-priority", Select)
        priority = priority_select.value

        project_select = self.query_one("#form-select-project", Select)
        project_id = project_select.value if isinstance(project_select.value, int) else None

        result: dict = {
            "title": title,
            "description": description,
            "priority": priority,
            "due_date": due_date,
            "project_id": project_id,
        }

        if self._mode == "create":
            column_select = self.query_one("#form-select-column", Select)
            result["column_id"] = column_select.value

        self.dismiss(result)

    def action_submit(self) -> None:
        self._submit()

    def action_cancel(self) -> None:
        self.dismiss(None)
