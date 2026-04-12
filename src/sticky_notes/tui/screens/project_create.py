from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Button, Footer, Input, Static

from sticky_notes.tui.screens.base_edit import BaseEditModal, ModalScroll
from sticky_notes.tui.widgets.markdown_editor import MarkdownEditor


class ProjectCreateModal(BaseEditModal):
    def compose(self) -> ComposeResult:
        with ModalScroll(classes="modal-container"):
            yield Static("New Project", classes="modal-id")

            yield Static("Name", classes="form-label")
            yield Input(
                placeholder="Project name",
                id="project-create-name",
                classes="form-field",
            )

            yield Static("Description (ctrl+e edit | ctrl+r preview)", classes="form-label")
            yield MarkdownEditor(
                "",
                id="project-create-desc",
                classes="form-field",
            )

            yield Static("", id="modal-error", classes="modal-error")
            with Horizontal(classes="modal-buttons"):
                yield Button("Save", variant="primary", id="modal-save")
                yield Button("Cancel", id="modal-cancel")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#project-create-name", Input).focus()

    def _do_save(self) -> None:
        name = self.query_one("#project-create-name", Input).value.strip()
        if not name:
            self._show_error("Name is required")
            return

        desc_text = self.query_one("#project-create-desc", MarkdownEditor).text.strip()
        description = desc_text or None

        self.dismiss({"name": name, "description": description})
