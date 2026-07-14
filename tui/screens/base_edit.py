"""BaseEditModal — ported from the old TUI. Common modal chrome + bindings; subclasses
implement _do_save() and dismiss with a result dict (or None to cancel)."""
from __future__ import annotations

from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.css.query import NoMatches
from textual.screen import ModalScreen
from textual.widgets import Button, Static

from ..widgets.markdown_editor import MarkdownEditor


class ModalScroll(VerticalScroll, can_focus=False):
    pass


class BaseEditModal(ModalScreen[dict | None]):
    BINDINGS = [
        Binding("escape", "dismiss", "Close", priority=True),
        Binding("ctrl+s", "save", "Save"),
        Binding("ctrl+n", "next_field", "Next", show=True),
        Binding("ctrl+b", "prev_field", "Prev", show=True),
        Binding("ctrl+e", "editor_mode", "Edit MD", show=True),
        Binding("ctrl+r", "preview_mode", "Preview MD", show=True),
    ]

    def action_dismiss(self) -> None:
        self.dismiss(None)

    def action_next_field(self) -> None:
        self.focus_next()

    def action_prev_field(self) -> None:
        self.focus_previous()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "modal-save":
            self.action_save()
        elif event.button.id == "modal-cancel":
            self.dismiss(None)

    def _show_error(self, msg: str) -> None:
        self.query_one("#modal-error", Static).update(msg)

    def _clear_error(self) -> None:
        self.query_one("#modal-error", Static).update("")

    def action_save(self) -> None:
        self._clear_error()
        self._do_save()

    def _do_save(self) -> None:  # pragma: no cover
        raise NotImplementedError

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
