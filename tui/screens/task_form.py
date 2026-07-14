"""Task create/edit modal. Status is intentionally NOT editable here — the daemon changes
status only through MoveStatus (transition-validated); use the board ([ / ]) for that. Create
may pick an initial status; edit covers title/description/priority/kind."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Button, Input, Label, Select, Static

from stxc.models import Kind, Status, Task
from ..widgets import MarkdownEditor
from .base_edit import BaseEditModal, ModalScroll


class TaskForm(BaseEditModal):
    def __init__(self, statuses: list[Status], kinds: list[Kind], task: Task | None = None) -> None:
        super().__init__()
        self._statuses = statuses
        self._kinds = kinds
        self._task_data = task

    def compose(self) -> ComposeResult:
        t = self._task_data
        with ModalScroll(classes="modal-container"):
            yield Static("Edit task" if t else "New task", classes="modal-id")
            yield Label("Title", classes="form-label")
            yield Input(value=t.title if t else "", id="f-title", classes="form-field")
            yield Label("Description", classes="form-label")
            yield MarkdownEditor(t.description if t else "", id="f-desc", classes="form-field")
            yield Label("Priority", classes="form-label")
            yield Input(value=str(t.priority if t else 0), id="f-priority", classes="form-field")
            if t is None:
                yield Label("Status", classes="form-label")
                yield Select(
                    [(s.name, s.id) for s in self._statuses],
                    value=next((s.id for s in self._statuses if s.is_default), Select.NULL),
                    allow_blank=True, id="f-status", classes="form-field",
                )
            yield Label("Kind", classes="form-label")
            yield Select(
                [(k.name, k.id) for k in self._kinds],
                value=(t.kind_id if t and t.kind_id else Select.NULL),
                allow_blank=True, id="f-kind", classes="form-field",
            )
            yield Static("", id="modal-error", classes="modal-error")
            with Horizontal(classes="modal-buttons"):
                yield Button("Save", id="modal-save", variant="primary")
                yield Button("Cancel", id="modal-cancel")

    def _do_save(self) -> None:
        title = self.query_one("#f-title", Input).value.strip()
        if not title:
            self._show_error("Title is required")
            return
        try:
            priority = int(self.query_one("#f-priority", Input).value.strip() or "0")
        except ValueError:
            self._show_error("Priority must be an integer")
            return
        kind_val = self.query_one("#f-kind", Select).value
        kind_id = None if kind_val is Select.NULL else int(kind_val)
        result: dict = {
            "title": title,
            "description": self.query_one("#f-desc", MarkdownEditor).text,
            "priority": priority,
            "kind_id": kind_id,
        }
        if self._task_data is None:
            status_val = self.query_one("#f-status", Select).value
            result["mode"] = "create"
            result["status_id"] = None if status_val is Select.NULL else int(status_val)
        else:
            result["mode"] = "edit"
            result["task_id"] = self._task_data.id
            result["expected_version"] = self._task_data.version
        self.dismiss(result)
