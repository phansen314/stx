"""Tests for the MarkdownEditor widget."""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.widgets import ContentSwitcher, TextArea

from sticky_notes.tui.widgets.markdown_editor import MarkdownEditor


class EditorTestApp(App):
    def __init__(self, text: str = "") -> None:
        super().__init__()
        self._text = text

    def compose(self) -> ComposeResult:
        yield MarkdownEditor(self._text, id="test-editor")


class TestMarkdownEditor:
    async def test_default_mode_is_editor(self):
        app = EditorTestApp("hello")
        async with app.run_test() as pilot:
            switcher = app.query_one(ContentSwitcher)
            assert switcher.current == "test-editor-editor"

    async def test_text_property_returns_content(self):
        app = EditorTestApp("hello")
        async with app.run_test() as pilot:
            editor = app.query_one(MarkdownEditor)
            assert editor.text == "hello"

    async def test_switch_to_preview(self):
        app = EditorTestApp("# Title")
        async with app.run_test() as pilot:
            editor = app.query_one(MarkdownEditor)
            editor.switch_to_preview()
            await pilot.pause()
            switcher = app.query_one(ContentSwitcher)
            assert switcher.current == "test-editor-preview"

    async def test_switch_back_to_editor_preserves_content(self):
        app = EditorTestApp("original")
        async with app.run_test() as pilot:
            editor = app.query_one(MarkdownEditor)
            editor.switch_to_preview()
            await pilot.pause()
            editor.switch_to_editor()
            await pilot.pause()
            assert editor.text == "original"

    async def test_text_property_works_in_preview_mode(self):
        app = EditorTestApp("still here")
        async with app.run_test() as pilot:
            editor = app.query_one(MarkdownEditor)
            editor.switch_to_preview()
            await pilot.pause()
            assert editor.text == "still here"

    async def test_preview_reflects_editor_changes(self):
        app = EditorTestApp("")
        async with app.run_test() as pilot:
            editor = app.query_one(MarkdownEditor)
            textarea = app.query_one(TextArea)
            textarea.insert("# Updated")
            editor.switch_to_preview()
            await pilot.pause()
            assert editor.text == "# Updated"

    async def test_editing_after_preview_roundtrip(self):
        app = EditorTestApp("start")
        async with app.run_test() as pilot:
            editor = app.query_one(MarkdownEditor)
            textarea = app.query_one(TextArea)
            editor.switch_to_preview()
            await pilot.pause()
            editor.switch_to_editor()
            await pilot.pause()
            textarea.clear()
            textarea.insert("changed")
            assert editor.text == "changed"
