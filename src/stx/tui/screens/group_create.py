from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Button, Footer, Input, Select, Static

from stx.models import Project
from stx.tui.screens.base_edit import BaseEditModal, ModalScroll
from stx.tui.widgets.markdown_editor import MarkdownEditor


class GroupCreateModal(BaseEditModal):
    def __init__(self, projects: tuple[Project, ...]) -> None:
        self._projects = projects
        super().__init__()

    def compose(self) -> ComposeResult:
        project_options = [(p.name, p.id) for p in self._projects]

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

            yield Static("Project", classes="form-label")
            yield Select(
                project_options,
                value=self._projects[0].id if self._projects else Select.NULL,
                id="group-create-project",
                allow_blank=False,
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

        project_val = self.query_one("#group-create-project", Select).value
        if not isinstance(project_val, int):
            self._show_error("Project is required")
            return

        desc_text = self.query_one("#group-create-desc", MarkdownEditor).text.strip()
        description = desc_text or None

        self.dismiss({"project_id": project_val, "title": title, "description": description})
