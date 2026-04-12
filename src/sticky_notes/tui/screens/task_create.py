from __future__ import annotations

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Footer, Input, Select, Static

from sticky_notes.models import Status
from sticky_notes.tui.model import ProjectNode, flatten_group_tree
from sticky_notes.tui.screens.base_edit import BaseEditModal, ModalScroll
from sticky_notes.tui.widgets.markdown_editor import MarkdownEditor


class TaskCreateModal(BaseEditModal):
    def __init__(
        self,
        statuses: tuple[Status, ...],
        project_nodes: tuple[ProjectNode, ...],
    ) -> None:
        self._statuses = statuses
        self._project_nodes = project_nodes
        self._groups_by_project: dict[int, list[tuple[str, int]]] = {
            node.project.id: flatten_group_tree(node.groups) for node in project_nodes
        }
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
            project_options = [(node.project.name, node.project.id) for node in self._project_nodes]

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
                    yield Static("Project", classes="form-label")
                    yield Select(
                        project_options,
                        value=Select.NULL,
                        id="task-create-project",
                        allow_blank=True,
                        classes="form-field",
                    )
                with Vertical(classes="form-group"):
                    yield Static("Group", classes="form-label")
                    yield Select(
                        [],
                        value=Select.NULL,
                        id="task-create-group",
                        allow_blank=True,
                        classes="form-field",
                        disabled=True,
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
        # Create modal starts with no project selected, so initial group
        # state matches compose (empty + disabled). Track project so the
        # mount-time Select.Changed echo is recognised as a no-op.
        self._last_project_id: int | None = None

    @on(Select.Changed, "#task-create-project")
    def _on_project_changed(self, event: Select.Changed) -> None:
        new_project = event.value if isinstance(event.value, int) else None
        if not hasattr(self, "_last_project_id") or new_project == self._last_project_id:
            self._last_project_id = new_project
            return
        self._last_project_id = new_project
        group_select = self.query_one("#task-create-group", Select)
        if new_project is not None:
            options = self._groups_by_project.get(new_project, [])
            group_select.set_options(options)
            group_select.disabled = not options
        else:
            group_select.set_options([])
            group_select.disabled = True

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
                "project_id": project_id,
                "group_id": group_id,
                "description": description,
                "due_date": due_date,
                "start_date": start_date,
                "finish_date": finish_date,
            }
        )
