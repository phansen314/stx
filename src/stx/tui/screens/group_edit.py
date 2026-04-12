from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Button, Footer, Input, Static

from stx.service_models import GroupDetail
from stx.tui.screens.base_edit import BaseEditModal, ModalScroll
from stx.tui.widgets.markdown_editor import MarkdownEditor


class GroupEditModal(BaseEditModal):
    def __init__(self, detail: GroupDetail) -> None:
        self.detail = detail
        super().__init__()

    def compose(self) -> ComposeResult:
        with ModalScroll(classes="modal-container"):
            yield Static(str(self.detail.id), classes="modal-id")

            yield Static("Title", classes="form-label")
            yield Input(
                value=self.detail.title,
                placeholder="Group title",
                id="group-edit-title",
                classes="form-field",
            )

            yield Static("Description (ctrl+e edit | ctrl+r preview)", classes="form-label")
            yield MarkdownEditor(
                self.detail.description or "",
                id="group-edit-desc",
                classes="form-field",
            )

            yield Static("", id="modal-error", classes="modal-error")
            with Horizontal(classes="modal-buttons"):
                yield Button("Save", variant="primary", id="modal-save")
                yield Button("Cancel", id="modal-cancel")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#group-edit-title", Input).focus()

    def _do_save(self) -> None:
        title = self.query_one("#group-edit-title", Input).value.strip()
        if not title:
            self._show_error("Title is required")
            return

        desc_text = self.query_one("#group-edit-desc", MarkdownEditor).text.strip()
        description = desc_text or None

        self._diff_and_dismiss(
            "group_id",
            self.detail.id,
            self.detail,
            {
                "title": title,
                "description": description,
            },
        )
