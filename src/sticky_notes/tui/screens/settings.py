from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.containers import Vertical, Horizontal
from textual import on
from textual.screen import Screen
from textual.widgets import Header, Footer, Static, Select, Switch, Rule

from sticky_notes import service
from sticky_notes.active_board import get_active_board_id, set_active_board_id
from sticky_notes.tui.config import save_config

if TYPE_CHECKING:
    from sticky_notes.tui.app import StickyNotesApp


class SettingsScreen(Screen):
    BINDINGS = [("escape", "app.pop_screen", "Back")]

    @property
    def typed_app(self) -> StickyNotesApp:
        return self.app  # type: ignore[return-value]

    def compose(self) -> ComposeResult:
        config = self.typed_app.config
        yield Header()
        yield Vertical(
            Static("Settings", classes="section-title"),
            Rule(),
            # ---- Database info ----
            Static("Database", classes="section-heading"),
            Static(id="db-path"),
            Static(id="db-size"),
            Rule(),
            # ---- Active board ----
            Static("Active Board", classes="section-heading"),
            Horizontal(
                Static("Board:", classes="label"),
                Select([], id="board-select"),
                classes="setting-row",
            ),
            Rule(),
            # ---- Display preferences ----
            Static("Display", classes="section-heading"),
            Horizontal(
                Static("Theme:", classes="label"),
                Select(
                    [("Dark", "dark"), ("Light", "light")],
                    id="theme-select",
                    value=config.theme,
                    allow_blank=False,
                ),
                classes="setting-row",
            ),
            Horizontal(
                Static("Show task descriptions:", classes="label"),
                Switch(id="show-descriptions", value=config.show_task_descriptions),
                classes="setting-row",
            ),
            Horizontal(
                Static("Show archived items:", classes="label"),
                Switch(id="show-archived", value=config.show_archived),
                classes="setting-row",
            ),
            Rule(),
            # ---- Behavior preferences ----
            Static("Behavior", classes="section-heading"),
            Horizontal(
                Static("Confirm before archive:", classes="label"),
                Switch(id="confirm-archive", value=config.confirm_archive),
                classes="setting-row",
            ),
            Horizontal(
                Static("Default priority:", classes="label"),
                Select(
                    [(str(i), i) for i in range(1, 6)],
                    id="priority-select",
                    value=config.default_priority,
                    allow_blank=False,
                ),
                classes="setting-row",
            ),
            id="settings-container",
        )
        yield Footer()

    def on_mount(self) -> None:
        self._refresh_db_info()
        self._refresh_board_select()

    def _refresh_db_info(self) -> None:
        db_path = self.typed_app.db_path
        self.query_one("#db-path", Static).update(f"  Path: {db_path}")
        if db_path.exists():
            size_bytes = os.path.getsize(db_path)
            if size_bytes < 1024:
                size_str = f"{size_bytes} B"
            elif size_bytes < 1024 * 1024:
                size_str = f"{size_bytes / 1024:.1f} KB"
            else:
                size_str = f"{size_bytes / (1024 * 1024):.1f} MB"
            self.query_one("#db-size", Static).update(f"  Size: {size_str}")
        else:
            self.query_one("#db-size", Static).update("  Size: (not found)")

    def _refresh_board_select(self) -> None:
        conn = self.typed_app.conn
        db_path = self.typed_app.db_path
        boards = service.list_boards(conn)
        options = [(b.name, b.id) for b in boards]
        select = self.query_one("#board-select", Select)
        select.set_options(options)
        active_id = get_active_board_id(db_path)
        if active_id is not None and any(b.id == active_id for b in boards):
            select.value = active_id
        elif boards:
            select.value = boards[0].id

    @on(Select.Changed, "#board-select")
    def _on_board_changed(self, event: Select.Changed) -> None:
        if event.value is not Select.BLANK:
            set_active_board_id(self.typed_app.db_path, event.value)

    @on(Select.Changed, "#theme-select")
    def _on_theme_changed(self, event: Select.Changed) -> None:
        if event.value is not Select.BLANK:
            config = self.typed_app.config
            config.theme = event.value
            self.typed_app.dark = event.value == "dark"
            save_config(config)

    @on(Select.Changed, "#priority-select")
    def _on_priority_changed(self, event: Select.Changed) -> None:
        if event.value is not Select.BLANK:
            config = self.typed_app.config
            config.default_priority = event.value
            save_config(config)

    @on(Switch.Changed, "#show-descriptions")
    def _on_show_descriptions_changed(self, event: Switch.Changed) -> None:
        self.typed_app.config.show_task_descriptions = event.value
        save_config(self.typed_app.config)

    @on(Switch.Changed, "#show-archived")
    def _on_show_archived_changed(self, event: Switch.Changed) -> None:
        self.typed_app.config.show_archived = event.value
        save_config(self.typed_app.config)

    @on(Switch.Changed, "#confirm-archive")
    def _on_confirm_archive_changed(self, event: Switch.Changed) -> None:
        self.typed_app.config.confirm_archive = event.value
        save_config(self.typed_app.config)
