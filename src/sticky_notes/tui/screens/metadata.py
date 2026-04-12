from __future__ import annotations

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Button, Footer, Input, Static

from sticky_notes.tui.screens.base_edit import BaseEditModal, ModalScroll


class MetadataModal(BaseEditModal):
    """Generic key/value metadata editor. Used for tasks, workspaces,
    projects, and groups — the caller supplies an already-formatted header
    label, the initial metadata dict, and the result-payload key to identify
    which entity kind dismissed the modal.
    """

    def __init__(
        self,
        *,
        display_title: str,
        metadata: dict[str, str],
        result_key: str,
        entity_id: int,
    ) -> None:
        self._display_title = display_title
        self._original_metadata = dict(metadata)
        self._result_key = result_key
        self._entity_id = entity_id
        self._row_counter = 0
        super().__init__()

    def compose(self) -> ComposeResult:
        with ModalScroll(classes="modal-container"):
            yield Static(self._display_title, classes="modal-id")

            with VerticalScroll(id="metadata-rows"):
                for key, value in sorted(self._original_metadata.items()):
                    yield self._build_row(key, value)
                if not self._original_metadata:
                    yield self._build_row("", "")

            with Horizontal(classes="metadata-add-row"):
                yield Button("+ Add row", id="metadata-add")

            yield Static("", id="modal-error", classes="modal-error")
            with Horizontal(classes="modal-buttons"):
                yield Button("Save", variant="primary", id="modal-save")
                yield Button("Cancel", id="modal-cancel")
        yield Footer()

    def _build_row(self, key: str, value: str) -> Horizontal:
        n = self._row_counter
        self._row_counter += 1
        row = Horizontal(
            Input(
                value=key,
                placeholder="key",
                id=f"metadata-key-{n}",
                classes="metadata-key form-field",
            ),
            Input(
                value=value,
                placeholder="value",
                id=f"metadata-value-{n}",
                classes="metadata-value form-field",
            ),
            Button(
                "\u00d7",
                id=f"metadata-del-{n}",
                classes="metadata-delete",
            ),
            id=f"metadata-row-{n}",
            classes="metadata-row",
        )
        return row

    def on_mount(self) -> None:
        first_key = self.query(".metadata-key").first()
        if first_key is not None:
            first_key.focus()

    @on(Button.Pressed, "#metadata-add")
    async def _on_add_row(self, event: Button.Pressed) -> None:
        event.stop()
        rows = self.query_one("#metadata-rows", VerticalScroll)
        row = self._build_row("", "")
        await rows.mount(row)
        row.query_one(".metadata-key", Input).focus()

    @on(Button.Pressed, ".metadata-delete")
    def _on_delete_row(self, event: Button.Pressed) -> None:
        event.stop()
        node = event.button
        while node is not None and "metadata-row" not in node.classes:
            node = node.parent  # type: ignore[assignment]
        if node is not None:
            node.remove()

    def _do_save(self) -> None:
        new_metadata: dict[str, str] = {}
        seen_normalized: set[str] = set()
        for idx, row in enumerate(self.query(".metadata-row"), start=1):
            key = row.query_one(".metadata-key", Input).value.strip()
            value = row.query_one(".metadata-value", Input).value
            if not key and not value:
                continue
            if not key:
                self._show_error(f"row {idx}: value without key")
                return
            normalized = key.lower()
            if normalized in seen_normalized:
                self._show_error(f"row {idx}: duplicate key {normalized!r}")
                return
            seen_normalized.add(normalized)
            new_metadata[key] = value

        # Compare normalized forms: the stored metadata is already lowercase
        # (service normalizes on write), so retyping a key in a different
        # case shouldn't count as a change.
        new_normalized = {k.lower(): v for k, v in new_metadata.items()}
        if new_normalized == self._original_metadata:
            self.dismiss(None)
            return
        self.dismiss({self._result_key: self._entity_id, "metadata": new_metadata})
