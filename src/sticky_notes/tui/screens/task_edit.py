from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Label, TextArea

from sticky_notes.service_models import TaskDetail


class TaskEditModal(ModalScreen):
    BINDINGS = [Binding("escape", "dismiss", "Close")]

    def __init__(self, detail: TaskDetail) -> None:
        self.detail = detail
        super().__init__()

    def compose(self) -> ComposeResult:
        with Vertical(id="task-edit-container"):
            yield Label(str(self.detail.id), id="task-edit-id")
            yield TextArea(self.detail.title, id="task-edit-title")
            yield TextArea(
                self.detail.description or "",
                id="task-edit-description",
            )
