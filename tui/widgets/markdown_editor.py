from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widget import Widget
from textual.widgets import ContentSwitcher, Markdown, TextArea


class _PreviewScroll(VerticalScroll, can_focus=False):
    pass


class MarkdownEditor(Widget):
    """TextArea editor + Markdown preview, toggled via ContentSwitcher."""

    def __init__(
        self, text: str = "", *, id: str | None = None, classes: str | None = None
    ) -> None:
        super().__init__(id=id, classes=classes)
        self._initial_text = text
        pfx = id or "md"
        self._editor_id = f"{pfx}-editor"
        self._preview_id = f"{pfx}-preview"

    def compose(self) -> ComposeResult:
        with ContentSwitcher(initial=self._editor_id):
            yield TextArea(self._initial_text, id=self._editor_id, tab_behavior="indent")
            with _PreviewScroll(id=self._preview_id):
                yield Markdown(self._initial_text)

    @property
    def text(self) -> str:
        return self.query_one(TextArea).text

    def switch_to_editor(self) -> None:
        self.query_one(ContentSwitcher).current = self._editor_id
        self.query_one(TextArea).focus()

    def switch_to_preview(self) -> None:
        self.query_one(Markdown).update(self.text)
        self.query_one(ContentSwitcher).current = self._preview_id
