from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Footer, Input, Select, Static

from stx.models import Status
from stx.tui.screens.base_edit import BaseEditModal, ModalScroll
from stx.tui.widgets.markdown_editor import MarkdownEditor


class TaskCreateModal(BaseEditModal):
    def __init__(
        self,
        statuses: tuple[Status, ...],
        group_options: list[tuple[str, int]],
    ) -> None:
        self._statuses = statuses
        self._group_options = group_options
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

            yield Static("Description (ctrl+e edit | ctrl+r preview)", classes="form-label")
            yield MarkdownEditor(
                "",
                id="task-create-desc",
                classes="form-field",
            )

            status_options = [(s.name, s.id) for s in self._statuses]
            priority_options = [(str(i), i) for i in range(1, 6)]

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

            with Horizontal(classes="form-row"):
                with Vertical(classes="form-group"):
                    yield Static("Group (optional)", classes="form-label")
                    yield Select(
                        self._group_options,
                        value=Select.NULL,
                        id="task-create-group",
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

        group_val = self.query_one("#task-create-group", Select).value
        group_id = group_val if isinstance(group_val, int) else None

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

        self.dismiss(
            {
                "title": title,
                "status_id": status_id,
                "priority": priority,
                "group_id": group_id,
                "description": description,
                "due_date": due_date,
                "start_date": start_date,
                "finish_date": finish_date,
            }
        )
