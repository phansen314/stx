from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Footer, Input, Label, Select, Static, TextArea

from sticky_notes.formatting import format_timestamp, parse_date
from sticky_notes.models import Project, Status
from sticky_notes.service_models import TaskDetail


class TaskEditModal(ModalScreen[dict | None]):
    BINDINGS = [
        Binding("escape", "dismiss", "Close", priority=True),
        Binding("ctrl+s", "save", "Save"),
        Binding("ctrl+n", "next_field", "Next", show=True),
        Binding("ctrl+m", "prev_field", "Prev", show=True),
    ]

    def __init__(
        self,
        detail: TaskDetail,
        statuses: tuple[Status, ...],
        projects: tuple[Project, ...],
    ) -> None:
        self.detail = detail
        self._statuses = statuses
        self._projects = projects
        super().__init__()

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="task-edit-container"):
            yield Label(str(self.detail.id), id="task-edit-id")

            yield Static("Title", classes="form-label")
            yield Input(
                value=self.detail.title,
                placeholder="Task title",
                id="task-edit-title",
                classes="form-field",
            )

            yield Static("Description", classes="form-label")
            yield TextArea(
                self.detail.description or "",
                id="task-edit-desc",
                classes="form-field",
                tab_behavior="indent",
            )

            status_options = [(s.name, s.id) for s in self._statuses]
            priority_options = [(str(i), i) for i in range(1, 6)]
            project_options = [(p.name, p.id) for p in self._projects]

            with Horizontal(classes="form-row"):
                with Vertical(classes="form-group"):
                    yield Static("Status", classes="form-label")
                    yield Select(
                        status_options,
                        value=self.detail.status_id,
                        id="task-edit-status",
                        allow_blank=False,
                        classes="form-field",
                    )
                with Vertical(classes="form-group"):
                    yield Static("Priority", classes="form-label")
                    yield Select(
                        priority_options,
                        value=self.detail.priority,
                        id="task-edit-priority",
                        allow_blank=False,
                        classes="form-field",
                    )
                with Vertical(classes="form-group"):
                    yield Static("Project", classes="form-label")
                    yield Select(
                        project_options,
                        value=self.detail.project_id if self.detail.project_id else Select.NULL,
                        id="task-edit-project",
                        allow_blank=True,
                        classes="form-field",
                    )

            due_str = format_timestamp(self.detail.due_date) if self.detail.due_date else ""
            start_str = format_timestamp(self.detail.start_date) if self.detail.start_date else ""
            finish_str = format_timestamp(self.detail.finish_date) if self.detail.finish_date else ""

            with Horizontal(classes="form-row"):
                with Vertical(classes="form-group"):
                    yield Static("Due Date", classes="form-label")
                    yield Input(
                        value=due_str,
                        placeholder="YYYY-MM-DD",
                        id="task-edit-due",
                        classes="form-field",
                    )
                with Vertical(classes="form-group"):
                    yield Static("Start Date", classes="form-label")
                    yield Input(
                        value=start_str,
                        placeholder="YYYY-MM-DD",
                        id="task-edit-start",
                        classes="form-field",
                    )
                with Vertical(classes="form-group"):
                    yield Static("Finish Date", classes="form-label")
                    yield Input(
                        value=finish_str,
                        placeholder="YYYY-MM-DD",
                        id="task-edit-finish",
                        classes="form-field",
                    )

            yield Static("", id="task-edit-error")
            with Horizontal(id="task-edit-buttons"):
                yield Button("Save", variant="primary", id="task-edit-save")
                yield Button("Cancel", id="task-edit-cancel")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#task-edit-title", Input).focus()

    def action_next_field(self) -> None:
        self.focus_next()

    def action_prev_field(self) -> None:
        self.focus_previous()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "task-edit-save":
            self.action_save()
        elif event.button.id == "task-edit-cancel":
            self.dismiss(None)

    def _show_error(self, msg: str) -> None:
        self.query_one("#task-edit-error", Static).update(msg)

    def _parse_date_field(self, field_id: str) -> int | None | str:
        """Return parsed timestamp, None for empty, or error string."""
        raw = self.query_one(f"#{field_id}", Input).value.strip()
        if not raw:
            return None
        try:
            return parse_date(raw)
        except ValueError:
            return f"Invalid date format in {field_id.replace('task-edit-', '')}"

    def action_save(self) -> None:
        # Read values
        title = self.query_one("#task-edit-title", Input).value.strip()
        if not title:
            self._show_error("Title is required")
            return

        desc_text = self.query_one("#task-edit-desc", TextArea).text.strip()
        description = desc_text or None

        status_id = self.query_one("#task-edit-status", Select).value
        priority = self.query_one("#task-edit-priority", Select).value

        project_val = self.query_one("#task-edit-project", Select).value
        project_id = project_val if isinstance(project_val, int) else None

        # Parse dates
        due_date = self._parse_date_field("task-edit-due")
        if isinstance(due_date, str):
            self._show_error(due_date)
            return
        start_date = self._parse_date_field("task-edit-start")
        if isinstance(start_date, str):
            self._show_error(start_date)
            return
        finish_date = self._parse_date_field("task-edit-finish")
        if isinstance(finish_date, str):
            self._show_error(finish_date)
            return

        # Validate date ordering
        if start_date is not None and finish_date is not None and finish_date < start_date:
            self._show_error("Finish date must be on or after start date")
            return

        # Diff against original
        form_values: dict[str, Any] = {
            "title": title,
            "description": description,
            "status_id": status_id,
            "priority": priority,
            "project_id": project_id,
            "due_date": due_date,
            "start_date": start_date,
            "finish_date": finish_date,
        }

        changes: dict[str, Any] = {}
        for field, new_val in form_values.items():
            old_val = getattr(self.detail, field)
            if new_val != old_val:
                changes[field] = new_val

        if not changes:
            self.dismiss(None)
            return

        self.dismiss({"task_id": self.detail.id, "changes": changes})
