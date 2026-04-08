from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Footer, Input, Select, Static

from sticky_notes.formatting import format_timestamp
from sticky_notes.models import Project, Status
from sticky_notes.service_models import TaskDetail
from sticky_notes.tui.screens.base_edit import BaseEditModal, ModalScroll
from sticky_notes.tui.widgets.markdown_editor import MarkdownEditor


class TaskEditModal(BaseEditModal):
    BINDINGS = BaseEditModal.BINDINGS + [
        Binding("alt+e", "editor_mode", "Edit MD", show=True),
        Binding("alt+p", "preview_mode", "Preview MD", show=True),
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
        with ModalScroll(classes="modal-container"):
            yield Static(str(self.detail.id), classes="modal-id")

            yield Static("Title", classes="form-label")
            yield Input(
                value=self.detail.title,
                placeholder="Task title",
                id="task-edit-title",
                classes="form-field",
            )

            yield Static("Description (alt+e edit | alt+p preview)", classes="form-label")
            yield MarkdownEditor(
                self.detail.description or "",
                id="task-edit-desc",
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

            if self.detail.blocked_by:
                names = ", ".join(f"{t.id}: {t.title}" for t in self.detail.blocked_by)
                yield Static(f"Blocked by: {names}", classes="form-label dep-info")
            if self.detail.blocks:
                names = ", ".join(f"{t.id}: {t.title}" for t in self.detail.blocks)
                yield Static(f"Blocks: {names}", classes="form-label dep-info")

            yield Static("", id="modal-error", classes="modal-error")
            with Horizontal(classes="modal-buttons"):
                yield Button("Save", variant="primary", id="modal-save")
                yield Button("Cancel", id="modal-cancel")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#task-edit-title", Input).focus()

    def _do_save(self) -> None:
        title = self.query_one("#task-edit-title", Input).value.strip()
        if not title:
            self._show_error("Title is required")
            return

        desc_text = self.query_one("#task-edit-desc", MarkdownEditor).text.strip()
        description = desc_text or None

        status_id = self.query_one("#task-edit-status", Select).value
        priority = self.query_one("#task-edit-priority", Select).value

        project_val = self.query_one("#task-edit-project", Select).value
        project_id = project_val if isinstance(project_val, int) else None

        due_date = self._parse_date_field("task-edit-due", "due")
        if isinstance(due_date, str):
            self._show_error(due_date)
            return
        start_date = self._parse_date_field("task-edit-start", "start")
        if isinstance(start_date, str):
            self._show_error(start_date)
            return
        finish_date = self._parse_date_field("task-edit-finish", "finish")
        if isinstance(finish_date, str):
            self._show_error(finish_date)
            return

        if start_date is not None and finish_date is not None and finish_date < start_date:
            self._show_error("Finish date must be on or after start date")
            return

        self._diff_and_dismiss("task_id", self.detail.id, self.detail, {
            "title": title,
            "description": description,
            "status_id": status_id,
            "priority": priority,
            "project_id": project_id,
            "due_date": due_date,
            "start_date": start_date,
            "finish_date": finish_date,
        })
