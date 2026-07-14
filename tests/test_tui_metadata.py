"""MetadataModal — prefill pretty-prints the current object; save returns canonical JSON and
blocks on invalid / non-object input. Daemon-free Pilot test, like test_tui_entity_edit."""
from __future__ import annotations

import json

import pytest

pytest.importorskip("textual")

from textual.app import App  # noqa: E402
from textual.widgets import TextArea  # noqa: E402

from tui.screens.metadata import MetadataModal  # noqa: E402

_UNSET = object()


class _Host(App):
    def __init__(self, modal: MetadataModal) -> None:
        super().__init__()
        self._modal = modal
        self.result = _UNSET

    def on_mount(self) -> None:
        self.push_screen(self._modal, callback=self._cb)

    def _cb(self, r) -> None:
        self.result = r


async def _run(modal: MetadataModal, drive) -> object:
    host = _Host(modal)
    async with host.run_test() as pilot:
        await pilot.pause()
        drive(modal)
        await pilot.pause()
    return host.result


class TestMetadata:
    @pytest.mark.asyncio
    async def test_prefill_pretty_prints(self) -> None:
        m = MetadataModal("Metadata — task", '{"b":2,"a":1}')

        def drive(mod: MetadataModal) -> None:
            mod._captured = mod.query_one("#md-json", TextArea).text

        await _run(m, drive)
        # sorted keys, indented
        assert m._captured == '{\n  "a": 1,\n  "b": 2\n}'

    @pytest.mark.asyncio
    async def test_save_returns_canonical_json_with_typed_values(self) -> None:
        def drive(m: MetadataModal) -> None:
            m.query_one("#md-json", TextArea).text = '{"tags": ["ui"], "n": 3, "ok": true}'
            m.action_save()

        result = await _run(MetadataModal("t", "{}"), drive)
        assert json.loads(result) == {"tags": ["ui"], "n": 3, "ok": True}

    @pytest.mark.asyncio
    async def test_empty_text_saves_empty_object(self) -> None:
        def drive(m: MetadataModal) -> None:
            m.query_one("#md-json", TextArea).text = ""
            m.action_save()

        assert await _run(MetadataModal("t", "{}"), drive) == "{}"

    @pytest.mark.asyncio
    async def test_invalid_json_blocks_dismiss(self) -> None:
        def drive(m: MetadataModal) -> None:
            m.query_one("#md-json", TextArea).text = "{not json"
            m.action_save()

        assert await _run(MetadataModal("t", "{}"), drive) is _UNSET

    @pytest.mark.asyncio
    async def test_non_object_blocks_dismiss(self) -> None:
        def drive(m: MetadataModal) -> None:
            m.query_one("#md-json", TextArea).text = "[1, 2, 3]"
            m.action_save()

        assert await _run(MetadataModal("t", "{}"), drive) is _UNSET
