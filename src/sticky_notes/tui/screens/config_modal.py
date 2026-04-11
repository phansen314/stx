from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Footer, Input, Select, Static

from sticky_notes.tui.config import TuiConfig
from sticky_notes.tui.screens.base_edit import BaseEditModal, ModalScroll


class ConfigModal(BaseEditModal):
    """TUI settings editor for theme and auto_refresh_seconds."""

    def __init__(
        self,
        *,
        config: TuiConfig,
        available_themes: tuple[str, ...],
    ) -> None:
        self._original_theme = config.theme
        self._original_interval = config.auto_refresh_seconds
        self._available_themes = available_themes
        super().__init__()

    def compose(self) -> ComposeResult:
        with ModalScroll(classes="modal-container"):
            yield Static("Settings", classes="modal-id")

            theme_options = [(t, t) for t in sorted(self._available_themes)]
            with Vertical(classes="form-group"):
                yield Static("Theme", classes="form-label")
                yield Select(
                    theme_options,
                    value=self._original_theme if self._original_theme in self._available_themes else Select.NULL,
                    id="config-theme",
                    allow_blank=False,
                    classes="form-field",
                )

            with Vertical(classes="form-group"):
                yield Static("Auto-refresh (seconds)", classes="form-label")
                yield Input(
                    value=str(self._original_interval),
                    placeholder="e.g. 30",
                    id="config-refresh",
                    classes="form-field",
                )

            yield Static("", id="modal-error", classes="modal-error")
            with Horizontal(classes="modal-buttons"):
                yield Button("Save", variant="primary", id="modal-save")
                yield Button("Cancel", id="modal-cancel")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#config-refresh", Input).focus()

    def _do_save(self) -> None:
        theme_val = self.query_one("#config-theme", Select).value
        if theme_val is Select.NULL:
            self._show_error("Theme is required")
            return

        raw_interval = self.query_one("#config-refresh", Input).value.strip()
        try:
            interval = int(raw_interval)
        except ValueError:
            self._show_error(f"Auto-refresh must be a positive integer, got {raw_interval!r}")
            return
        if interval <= 0:
            self._show_error(f"Auto-refresh must be a positive integer, got {interval}")
            return

        changes: dict = {}
        if theme_val != self._original_theme:
            changes["theme"] = theme_val
        if interval != self._original_interval:
            changes["auto_refresh_seconds"] = interval

        self.dismiss({"changes": changes} if changes else None)
