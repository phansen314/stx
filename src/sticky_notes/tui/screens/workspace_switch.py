from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, Footer, Label, Select, Static

from sticky_notes.models import Workspace


class WorkspaceSwitchModal(ModalScreen[int | None]):
    BINDINGS = [
        Binding("escape", "dismiss", "Close", priority=True),
    ]

    def __init__(
        self,
        workspaces: tuple[Workspace, ...],
        current_id: int,
    ) -> None:
        self._workspaces = workspaces
        self._current_id = current_id
        super().__init__()

    def compose(self) -> ComposeResult:
        with Static(classes="modal-container"):
            yield Label("Switch Workspace", classes="modal-id")
            yield Select(
                [(w.name, w.id) for w in self._workspaces],
                value=self._current_id,
                id="workspace-switch-select",
                allow_blank=False,
            )
            yield Static("", id="modal-error", classes="modal-error")
            with Horizontal(classes="modal-buttons"):
                yield Button("Switch", variant="primary", id="workspace-switch-go")
                yield Button("Cancel", id="workspace-switch-cancel")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#workspace-switch-select", Select).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "workspace-switch-go":
            val = self.query_one("#workspace-switch-select", Select).value
            if isinstance(val, int):
                self.dismiss(val)
        elif event.button.id == "workspace-switch-cancel":
            self.dismiss(None)
