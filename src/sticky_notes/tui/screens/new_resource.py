from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, Footer, Label, Static


class NewResourceModal(ModalScreen[str | None]):
    BINDINGS = [
        Binding("t", "select('task')", "Task", show=True),
        Binding("g", "select('group')", "Group", show=True),
        Binding("p", "select('project')", "Project", show=True),
        Binding("s", "select('status')", "Status", show=True),
        Binding("w", "select('workspace')", "Workspace", show=True),
        Binding("escape", "dismiss", "Close", priority=True),
    ]

    def compose(self) -> ComposeResult:
        with Static(classes="modal-container selector-modal"):
            yield Label("Create New...", classes="modal-id")
            with Horizontal(classes="modal-buttons"):
                yield Button("(t)ask", id="new-task")
                yield Button("(g)roup", id="new-group")
                yield Button("(p)roject", id="new-project")
                yield Button("(s)tatus", id="new-status")
                yield Button("(w)orkspace", id="new-workspace")
        yield Footer()

    def action_select(self, resource_type: str) -> None:
        self.dismiss(resource_type)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        mapping = {
            "new-task": "task",
            "new-group": "group",
            "new-project": "project",
            "new-status": "status",
            "new-workspace": "workspace",
        }
        resource_type = mapping.get(event.button.id)  # type: ignore[arg-type]
        if resource_type is not None:
            self.dismiss(resource_type)
