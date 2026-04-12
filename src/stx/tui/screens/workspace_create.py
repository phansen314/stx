from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Button, Footer, Input, Static

from stx.tui.screens.base_edit import BaseEditModal, ModalScroll


class WorkspaceCreateModal(BaseEditModal):
    def compose(self) -> ComposeResult:
        with ModalScroll(classes="modal-container"):
            yield Static("New Workspace", classes="modal-id")

            yield Static("Name", classes="form-label")
            yield Input(
                placeholder="Workspace name",
                id="workspace-create-name",
                classes="form-field",
            )

            yield Static("", id="modal-error", classes="modal-error")
            with Horizontal(classes="modal-buttons"):
                yield Button("Save", variant="primary", id="modal-save")
                yield Button("Cancel", id="modal-cancel")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#workspace-create-name", Input).focus()

    def _do_save(self) -> None:
        name = self.query_one("#workspace-create-name", Input).value.strip()
        if not name:
            self._show_error("Name is required")
            return
        self.dismiss({"name": name})
