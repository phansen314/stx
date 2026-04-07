from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Static

from sticky_notes.models import Workspace


class WorkspaceEditModal(ModalScreen[dict | None]):
    BINDINGS = [
        Binding("escape", "dismiss", "Close", priority=True),
        Binding("ctrl+s", "save", "Save"),
        Binding("ctrl+n", "next_field", "Next", show=True),
        Binding("ctrl+m", "prev_field", "Prev", show=True),
    ]

    def __init__(self, workspace: Workspace) -> None:
        self.workspace = workspace
        super().__init__()

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="workspace-edit-container"):
            yield Label(str(self.workspace.id), id="workspace-edit-id")

            yield Static("Name", classes="form-label")
            yield Input(
                value=self.workspace.name,
                placeholder="Workspace name",
                id="workspace-edit-name",
                classes="form-field",
            )

            yield Static("", id="workspace-edit-error")
            with Horizontal(id="workspace-edit-buttons"):
                yield Button("Save", variant="primary", id="workspace-edit-save")
                yield Button("Cancel", id="workspace-edit-cancel")

    def on_mount(self) -> None:
        self.query_one("#workspace-edit-name", Input).focus()

    def action_next_field(self) -> None:
        self.focus_next()

    def action_prev_field(self) -> None:
        self.focus_previous()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "workspace-edit-save":
            self.action_save()
        elif event.button.id == "workspace-edit-cancel":
            self.dismiss(None)

    def _show_error(self, msg: str) -> None:
        self.query_one("#workspace-edit-error", Static).update(msg)

    def action_save(self) -> None:
        name = self.query_one("#workspace-edit-name", Input).value.strip()
        if not name:
            self._show_error("Name is required")
            return

        changes: dict[str, Any] = {}
        if name != self.workspace.name:
            changes["name"] = name

        if not changes:
            self.dismiss(None)
            return

        self.dismiss({"workspace_id": self.workspace.id, "changes": changes})
