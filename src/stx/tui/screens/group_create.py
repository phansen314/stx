from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Button, Footer, Input, Select, Static

from stx.tui.screens.base_edit import BaseEditModal, ModalScroll
from stx.tui.widgets.markdown_editor import MarkdownEditor


class GroupCreateModal(BaseEditModal):
    def __init__(self, workspace_id: int, group_options: list[tuple[str, int]]) -> None:
        self._workspace_id = workspace_id
        self._group_options = group_options
        super().__init__()

    def compose(self) -> ComposeResult:
        with ModalScroll(classes="modal-container"):
            yield Static("New Group", classes="modal-id")

            yield Static("Title", classes="form-label")
            yield Input(
                placeholder="Group title",
                id="group-create-title",
                classes="form-field",
            )

            yield Static("Description (ctrl+e edit | ctrl+r preview)", classes="form-label")
            yield MarkdownEditor(
                "",
                id="group-create-desc",
                classes="form-field",
            )

            yield Static("Parent Group (optional)", classes="form-label")
            yield Select(
                self._group_options,
                value=Select.NULL,
                id="group-create-parent",
                allow_blank=True,
                classes="form-field",
            )

            yield Static("", id="modal-error", classes="modal-error")
            with Horizontal(classes="modal-buttons"):
                yield Button("Save", variant="primary", id="modal-save")
                yield Button("Cancel", id="modal-cancel")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#group-create-title", Input).focus()

    def _do_save(self) -> None:
        title = self.query_one("#group-create-title", Input).value.strip()
        if not title:
            self._show_error("Title is required")
            return

        parent_val = self.query_one("#group-create-parent", Select).value
        parent_id = parent_val if isinstance(parent_val, int) else None

        desc_text = self.query_one("#group-create-desc", MarkdownEditor).text.strip()
        description = desc_text or None

        self.dismiss(
            {
                "workspace_id": self._workspace_id,
                "title": title,
                "parent_id": parent_id,
                "description": description,
            }
        )
