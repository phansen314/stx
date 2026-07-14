"""ConfigModal — pick the Textual theme (with live preview) and the auto-refresh interval.

Theme changes apply to the whole app immediately as you scroll the Select, so you see the re-skin;
Cancel reverts to the theme that was active on open, Save keeps it. Dismisses with
{"theme": str, "refresh_secs": float} or None on cancel; the app persists it (tui/config.py).
"""
from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Select, Static


class ConfigModal(ModalScreen[dict | None]):
    BINDINGS = [
        Binding("escape", "cancel", "Cancel", priority=True),
        Binding("ctrl+s", "save", "Save"),
    ]

    def __init__(self, current_theme: str, themes: list[str], refresh_secs: float) -> None:
        super().__init__()
        self._orig_theme = current_theme
        self._themes = themes
        self._refresh_secs = refresh_secs

    def compose(self) -> ComposeResult:
        with Vertical(classes="selector-modal"):
            yield Static("Config", classes="modal-id")
            yield Label("Theme", classes="form-label")
            yield Select(
                [(t, t) for t in self._themes],
                value=self._orig_theme, allow_blank=False, id="cfg-theme", classes="form-field",
            )
            yield Label("Auto-refresh (seconds)", classes="form-label")
            yield Input(value=str(self._refresh_secs), id="cfg-refresh", classes="form-field")
            yield Static("", id="modal-error", classes="modal-error")
            with Horizontal(classes="modal-buttons"):
                yield Button("Save", id="modal-save", variant="primary")
                yield Button("Cancel", id="modal-cancel")

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "cfg-theme" and event.value is not Select.NULL:
            self.app.theme = event.value  # live preview

    def action_cancel(self) -> None:
        self.app.theme = self._orig_theme  # revert the live preview
        self.dismiss(None)

    def action_save(self) -> None:
        try:
            secs = float(self.query_one("#cfg-refresh", Input).value.strip())
        except ValueError:
            self.query_one("#modal-error", Static).update("refresh must be a number")
            return
        if secs <= 0:
            self.query_one("#modal-error", Static).update("refresh must be > 0")
            return
        theme = self.query_one("#cfg-theme", Select).value
        self.dismiss({"theme": theme, "refresh_secs": secs})

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "modal-save":
            self.action_save()
        else:
            self.action_cancel()
