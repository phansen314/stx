from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, Footer, Label, Static


class ArchiveConfirmModal(ModalScreen[bool | None]):
    BINDINGS = [
        Binding("y", "confirm", "Yes", show=True),
        Binding("n", "cancel", "No", show=True),
        Binding("escape", "dismiss(None)", "Close", priority=True),
    ]

    def __init__(self, preview_text: str, entity_label: str) -> None:
        super().__init__()
        self._preview_text = preview_text
        self._entity_label = entity_label

    def compose(self) -> ComposeResult:
        with Static(classes="modal-container"):
            yield Label(f"Archive {self._entity_label}?", classes="modal-id")
            yield Static(self._preview_text, classes="archive-preview")
            with Horizontal(classes="modal-buttons"):
                yield Button("(n)o", id="archive-no", variant="primary")
                yield Button("(y)es", id="archive-yes", variant="error")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#archive-no", Button).focus()

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "archive-yes":
            self.dismiss(True)
        elif event.button.id == "archive-no":
            self.dismiss(False)
