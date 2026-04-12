from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Button, Footer, Input, Select, Static

from stx.models import Workspace
from stx.tui.screens.base_edit import BaseEditModal, ModalScroll


class StatusCreateModal(BaseEditModal):
    def __init__(
        self,
        workspaces: tuple[Workspace, ...],
        default_workspace_id: int | None,
    ) -> None:
        self._workspaces = workspaces
        self._default_ws_id = default_workspace_id
        super().__init__()

    def compose(self) -> ComposeResult:
        ws_options = [(ws.name, ws.id) for ws in self._workspaces]
        default_val = (
            self._default_ws_id
            if self._default_ws_id is not None
            else (self._workspaces[0].id if self._workspaces else Select.BLANK)
        )

        with ModalScroll(classes="modal-container"):
            yield Static("New Status", classes="modal-id")

            yield Static("Name", classes="form-label")
            yield Input(
                placeholder="Status name",
                id="status-create-name",
                classes="form-field",
            )

            yield Static("Workspace", classes="form-label")
            yield Select(
                ws_options,
                value=default_val,
                id="status-create-workspace",
                allow_blank=False,
                classes="form-field",
            )

            yield Static("", id="modal-error", classes="modal-error")
            with Horizontal(classes="modal-buttons"):
                yield Button("Save", variant="primary", id="modal-save")
                yield Button("Cancel", id="modal-cancel")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#status-create-name", Input).focus()

    def _do_save(self) -> None:
        name = self.query_one("#status-create-name", Input).value.strip()
        if not name:
            self._show_error("Name is required")
            return

        ws_val = self.query_one("#status-create-workspace", Select).value
        if not isinstance(ws_val, int):
            self._show_error("Workspace is required")
            return

        self.dismiss({"workspace_id": ws_val, "name": name})
