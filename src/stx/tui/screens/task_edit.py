from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Footer, Input, Select, Static

from stx.formatting import format_timestamp
from stx.models import Status
from stx.service_models import TaskDetail
from stx.tui.screens.base_edit import BaseEditModal, ModalScroll
from stx.tui.widgets.markdown_editor import MarkdownEditor


class TaskEditModal(BaseEditModal):
    def __init__(
        self,
        detail: TaskDetail,
        statuses: tuple[Status, ...],
        group_options: list[tuple[str, int]],
    ) -> None:
        self.detail = detail
        self._statuses = statuses
        self._group_options = group_options
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

            yield Static("Description (ctrl+e edit | ctrl+r preview)", classes="form-label")
            yield MarkdownEditor(
                self.detail.description or "",
                id="task-edit-desc",
                classes="form-field",
            )

            status_options = [(s.name, s.id) for s in self._statuses]
            priority_options = [(str(i), i) for i in range(1, 6)]

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

            group_ids = {gid for _, gid in self._group_options}
            initial_group = (
                self.detail.group_id
                if self.detail.group_id is not None and self.detail.group_id in group_ids
                else Select.NULL
            )

            with Horizontal(classes="form-row"):
                with Vertical(classes="form-group"):
                    yield Static("Group (optional)", classes="form-label")
                    yield Select(
                        self._group_options,
                        value=initial_group,
                        id="task-edit-group",
                        allow_blank=True,
                        classes="form-field",
                    )

            due_str = format_timestamp(self.detail.due_date) if self.detail.due_date else ""
            start_str = format_timestamp(self.detail.start_date) if self.detail.start_date else ""
            finish_str = (
                format_timestamp(self.detail.finish_date) if self.detail.finish_date else ""
            )

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

            if self.detail.edge_sources:
                names = ", ".join(
                    f"{ref.node_type}:{ref.node_id} {ref.node_title} ({ref.kind})"
                    for ref in self.detail.edge_sources
                )
                yield Static(f"Edge sources: {names}", classes="form-label dep-info")
            if self.detail.edge_targets:
                names = ", ".join(
                    f"{ref.node_type}:{ref.node_id} {ref.node_title} ({ref.kind})"
                    for ref in self.detail.edge_targets
                )
                yield Static(f"Edge targets: {names}", classes="form-label dep-info")

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

        group_val = self.query_one("#task-edit-group", Select).value
        group_id = group_val if isinstance(group_val, int) else None

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

        self._diff_and_dismiss(
            "task_id",
            self.detail.id,
            self.detail,
            {
                "title": title,
                "description": description,
                "status_id": status_id,
                "priority": priority,
                "group_id": group_id,
                "due_date": due_date,
                "start_date": start_date,
                "finish_date": finish_date,
            },
        )
