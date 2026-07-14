"""MetadataModal — edit an entity's free-form metadata as raw JSON.

Metadata is an opaque JSON object on workspaces/tracks/tasks (replace-whole on save). A raw JSON
editor keeps full fidelity — nested objects, arrays, numbers, bools all round-trip. Dismisses with
the canonical JSON string (or None to cancel); the app sends it via edit_*(…, metadata_json=…).
"""
from __future__ import annotations

import json

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, Static, TextArea

from .base_edit import ModalScroll


class MetadataModal(ModalScreen[str | None]):
    BINDINGS = [
        Binding("escape", "cancel", "Cancel", priority=True),
        Binding("ctrl+s", "save", "Save"),
    ]

    def __init__(self, title: str, metadata_json: str) -> None:
        super().__init__()
        self._title = title
        try:
            obj = json.loads(metadata_json or "{}")
        except ValueError:
            obj = {}
        self._initial = json.dumps(obj, indent=2, sort_keys=True)

    def compose(self) -> ComposeResult:
        with ModalScroll(classes="modal-container"):
            yield Static(self._title, classes="modal-id")
            yield TextArea(self._initial, id="md-json", tab_behavior="indent")
            yield Static("", id="modal-error", classes="modal-error")
            with Horizontal(classes="modal-buttons"):
                yield Button("Save", id="modal-save", variant="primary")
                yield Button("Cancel", id="modal-cancel")

    def action_cancel(self) -> None:
        self.dismiss(None)

    def _error(self, msg: str) -> None:
        self.query_one("#modal-error", Static).update(msg)

    def action_save(self) -> None:
        text = self.query_one("#md-json", TextArea).text
        try:
            obj = json.loads(text or "{}")
        except ValueError as e:
            self._error(f"invalid JSON: {e}")
            return
        if not isinstance(obj, dict):
            self._error("metadata must be a JSON object")
            return
        self.dismiss(json.dumps(obj))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "modal-save":
            self.action_save()
        else:
            self.dismiss(None)
