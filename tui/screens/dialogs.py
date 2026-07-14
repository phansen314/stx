"""Small modal dialogs: confirm, single-name prompt, new-resource chooser."""
from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Static

from ..widgets import MarkdownEditor


class ConfirmModal(ModalScreen[bool]):
    BINDINGS = [
        Binding("escape", "no", "No", priority=True),
        Binding("y", "yes", "Yes"),
        Binding("n", "no", "No"),
    ]

    def __init__(self, message: str) -> None:
        super().__init__()
        self._message = message

    def compose(self) -> ComposeResult:
        with Vertical(classes="selector-modal"):
            yield Static(self._message)
            with Horizontal(classes="modal-buttons"):
                yield Button("Yes", id="yes", variant="error")
                yield Button("No", id="no")

    def action_yes(self) -> None:
        self.dismiss(True)

    def action_no(self) -> None:
        self.dismiss(False)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "yes")


class NameModal(ModalScreen[str | None]):
    BINDINGS = [
        Binding("escape", "cancel", "Cancel", priority=True),
        Binding("ctrl+s", "save", "Save"),
    ]

    def __init__(self, title: str, label: str = "Name") -> None:
        super().__init__()
        self._title = title
        self._label = label

    def compose(self) -> ComposeResult:
        with Vertical(classes="selector-modal"):
            yield Static(self._title, classes="modal-id")
            yield Label(self._label, classes="form-label")
            yield Input(id="name", classes="form-field")
            with Horizontal(classes="modal-buttons"):
                yield Button("Save", id="modal-save", variant="primary")
                yield Button("Cancel", id="modal-cancel")

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_save(self) -> None:
        value = self.query_one("#name", Input).value.strip()
        self.dismiss(value or None)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.action_save()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "modal-save":
            self.action_save()
        else:
            self.dismiss(None)


class EntityEditModal(ModalScreen[dict | None]):
    """Rename a container. Name is required; description is shown only when passed (workspaces
    have none). Dismisses with {"name": ...} plus "description" when that field is present."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", priority=True),
        Binding("ctrl+s", "save", "Save"),
        Binding("ctrl+e", "editor_mode", "Edit MD", show=True),
        Binding("ctrl+r", "preview_mode", "Preview MD", show=True),
    ]

    def __init__(self, title: str, name: str, description: str | None = None) -> None:
        super().__init__()
        self._title = title
        self._name = name
        self._description = description  # None → hide the description field

    def compose(self) -> ComposeResult:
        with Vertical(classes="selector-modal"):
            yield Static(self._title, classes="modal-id")
            yield Label("Name", classes="form-label")
            yield Input(value=self._name, id="e-name", classes="form-field")
            if self._description is not None:
                yield Label("Description", classes="form-label")
                yield MarkdownEditor(self._description, id="e-desc", classes="form-field")
            yield Static("", id="modal-error", classes="modal-error")
            with Horizontal(classes="modal-buttons"):
                yield Button("Save", id="modal-save", variant="primary")
                yield Button("Cancel", id="modal-cancel")

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_save(self) -> None:
        name = self.query_one("#e-name", Input).value.strip()
        if not name:
            self.query_one("#modal-error", Static).update("Name is required")
            return
        result: dict = {"name": name}
        if self._description is not None:
            result["description"] = self.query_one("#e-desc", MarkdownEditor).text
        self.dismiss(result)

    def action_editor_mode(self) -> None:
        try:
            self.query_one(MarkdownEditor).switch_to_editor()
        except NoMatches:
            pass

    def action_preview_mode(self) -> None:
        try:
            self.query_one(MarkdownEditor).switch_to_preview()
        except NoMatches:
            pass

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.action_save()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "modal-save":
            self.action_save()
        else:
            self.dismiss(None)


class NewResourceModal(ModalScreen[str | None]):
    BINDINGS = [
        Binding("escape", "cancel", "Cancel", priority=True),
        Binding("t", "pick('task')", "Task"),
        Binding("s", "pick('segment')", "Segment"),
        Binding("r", "pick('track')", "Track"),
        Binding("w", "pick('workspace')", "Workspace"),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(classes="selector-modal"):
            yield Static("New…", classes="modal-id")
            with Horizontal(classes="modal-buttons"):
                yield Button("Task (t)", id="task", variant="primary")
                yield Button("Segment (s)", id="segment")
                yield Button("Track (r)", id="track")
                yield Button("Workspace (w)", id="workspace")

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_pick(self, what: str) -> None:
        self.dismiss(what)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id)
