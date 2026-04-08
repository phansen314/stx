from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Footer, Input, Select, Static

from sticky_notes.models import Project, Status
from sticky_notes.tui.screens.base_edit import BaseEditModal, ModalScroll
from sticky_notes.tui.widgets.markdown_editor import MarkdownEditor


class TaskCreateModal(BaseEditModal):
    BINDINGS = BaseEditModal.BINDINGS + [
        Binding("alt+e", "editor_mode", "Edit MD", show=True),
        Binding("alt+p", "preview_mode", "Preview MD", show=True),
    ]

    def __init__(
        self,
        statuses: tuple[Status, ...],
        projects: tuple[Project, ...],
    ) -> None:
        self._statuses = statuses
        self._projects = projects
        super().__init__()

    def compose(self) -> ComposeResult:
        with ModalScroll(classes="modal-container"):
            yield Static("New Task", classes="modal-id")

            yield Static("Title", classes="form-label")
            yield Input(
                placeholder="Task title",
                id="task-create-title",
                classes="form-field",
            )

            yield Static("Description (alt+e edit | alt+p preview)", classes="form-label")
            yield MarkdownEditor(
                "",
                id="task-create-desc",
                classes="form-field",
            )

            status_options = [(s.name, s.id) for s in self._statuses]
            priority_options = [(str(i), i) for i in range(1, 6)]
            project_options = [(p.name, p.id) for p in self._projects]

            with Horizontal(classes="form-row"):
                with Vertical(classes="form-group"):
                    yield Static("Status", classes="form-label")
                    yield Select(
                        status_options,
                        value=self._statuses[0].id if self._statuses else Select.NULL,
                        id="task-create-status",
                        allow_blank=False,
                        classes="form-field",
                    )
                with Vertical(classes="form-group"):
                    yield Static("Priority", classes="form-label")
                    yield Select(
                        priority_options,
                        value=1,
                        id="task-create-priority",
                        allow_blank=False,
                        classes="form-field",
                    )
                with Vertical(classes="form-group"):
                    yield Static("Project", classes="form-label")
                    yield Select(
                        project_options,
                        value=Select.NULL,
                        id="task-create-project",
                        allow_blank=True,
                        classes="form-field",
                    )

            with Horizontal(classes="form-row"):
                with Vertical(classes="form-group"):
                    yield Static("Due Date", classes="form-label")
                    yield Input(
                        placeholder="YYYY-MM-DD",
                        id="task-create-due",
                        classes="form-field",
                    )
                with Vertical(classes="form-group"):
                    yield Static("Start Date", classes="form-label")
                    yield Input(
                        placeholder="YYYY-MM-DD",
                        id="task-create-start",
                        classes="form-field",
                    )
                with Vertical(classes="form-group"):
                    yield Static("Finish Date", classes="form-label")
                    yield Input(
                        placeholder="YYYY-MM-DD",
                        id="task-create-finish",
                        classes="form-field",
                    )

            yield Static("", id="modal-error", classes="modal-error")
            with Horizontal(classes="modal-buttons"):
                yield Button("Save", variant="primary", id="modal-save")
                yield Button("Cancel", id="modal-cancel")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#task-create-title", Input).focus()

    def _do_save(self) -> None:
        title = self.query_one("#task-create-title", Input).value.strip()
        if not title:
            self._show_error("Title is required")
            return

        desc_text = self.query_one("#task-create-desc", MarkdownEditor).text.strip()
        description = desc_text or None

        status_id = self.query_one("#task-create-status", Select).value
        if not isinstance(status_id, int):
            self._show_error("Status is required")
            return

        priority = self.query_one("#task-create-priority", Select).value

        project_val = self.query_one("#task-create-project", Select).value
        project_id = project_val if isinstance(project_val, int) else None

        due_date = self._parse_date_field("task-create-due", "due")
        if isinstance(due_date, str):
            self._show_error(due_date)
            return
        start_date = self._parse_date_field("task-create-start", "start")
        if isinstance(start_date, str):
            self._show_error(start_date)
            return
        finish_date = self._parse_date_field("task-create-finish", "finish")
        if isinstance(finish_date, str):
            self._show_error(finish_date)
            return

        if start_date is not None and finish_date is not None and finish_date < start_date:
            self._show_error("Finish date must be on or after start date")
            return

        self.dismiss({
            "title": title,
            "status_id": status_id,
            "priority": priority,
            "project_id": project_id,
            "description": description,
            "due_date": due_date,
            "start_date": start_date,
            "finish_date": finish_date,
        })
