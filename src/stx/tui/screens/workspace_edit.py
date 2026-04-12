from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Button, Footer, Input, Static

from stx.models import Workspace
from stx.tui.screens.base_edit import BaseEditModal, ModalScroll


class WorkspaceEditModal(BaseEditModal):
    def __init__(self, workspace: Workspace) -> None:
        self.detail = workspace
        super().__init__()

    def compose(self) -> ComposeResult:
        with ModalScroll(classes="modal-container"):
            yield Static(str(self.detail.id), classes="modal-id")

            yield Static("Name", classes="form-label")
            yield Input(
                value=self.detail.name,
                placeholder="Workspace name",
                id="workspace-edit-name",
                classes="form-field",
            )

            yield Static("", id="modal-error", classes="modal-error")
            with Horizontal(classes="modal-buttons"):
                yield Button("Save", variant="primary", id="modal-save")
                yield Button("Cancel", id="modal-cancel")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#workspace-edit-name", Input).focus()

    def _do_save(self) -> None:
        name = self.query_one("#workspace-edit-name", Input).value.strip()
        if not name:
            self._show_error("Name is required")
            return

        self._diff_and_dismiss("workspace_id", self.detail.id, self.detail, {"name": name})
