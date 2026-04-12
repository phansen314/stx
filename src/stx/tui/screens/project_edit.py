from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Button, Footer, Input, Static

from stx.service_models import ProjectDetail
from stx.tui.screens.base_edit import BaseEditModal, ModalScroll
from stx.tui.widgets.markdown_editor import MarkdownEditor


class ProjectEditModal(BaseEditModal):
    def __init__(self, detail: ProjectDetail) -> None:
        self.detail = detail
        super().__init__()

    def compose(self) -> ComposeResult:
        with ModalScroll(classes="modal-container"):
            yield Static(str(self.detail.id), classes="modal-id")

            yield Static("Name", classes="form-label")
            yield Input(
                value=self.detail.name,
                placeholder="Project name",
                id="project-edit-name",
                classes="form-field",
            )

            yield Static("Description (ctrl+e edit | ctrl+r preview)", classes="form-label")
            yield MarkdownEditor(
                self.detail.description or "",
                id="project-edit-desc",
                classes="form-field",
            )

            yield Static("", id="modal-error", classes="modal-error")
            with Horizontal(classes="modal-buttons"):
                yield Button("Save", variant="primary", id="modal-save")
                yield Button("Cancel", id="modal-cancel")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#project-edit-name", Input).focus()

    def _do_save(self) -> None:
        name = self.query_one("#project-edit-name", Input).value.strip()
        if not name:
            self._show_error("Name is required")
            return

        desc_text = self.query_one("#project-edit-desc", MarkdownEditor).text.strip()
        description = desc_text or None

        self._diff_and_dismiss(
            "project_id",
            self.detail.id,
            self.detail,
            {
                "name": name,
                "description": description,
            },
        )
