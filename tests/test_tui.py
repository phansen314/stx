from __future__ import annotations

from pathlib import Path

import pytest

from sticky_notes.connection import DEFAULT_DB_PATH
from sticky_notes.tui.app import StickyNotesApp
from sticky_notes.tui.config import TuiConfig, load_config, save_config
from sticky_notes.tui.screens.settings import SettingsScreen
from textual.widgets import Static


# ---- Config unit tests ----


class TestTuiConfig:
    def test_defaults(self):
        config = TuiConfig()
        assert config.theme == "dark"
        assert config.show_task_descriptions is True
        assert config.show_archived is False
        assert config.confirm_archive is True
        assert config.default_priority == 1

    def test_load_missing_file(self, tmp_path: Path):
        config = load_config(tmp_path / "nonexistent.toml")
        assert config == TuiConfig()

    def test_save_load_roundtrip(self, tmp_path: Path):
        path = tmp_path / "tui.toml"
        original = TuiConfig(
            theme="light",
            show_task_descriptions=False,
            show_archived=True,
            confirm_archive=False,
            default_priority=3,
        )
        save_config(original, path)
        loaded = load_config(path)
        assert loaded.theme == "light"
        assert loaded.show_task_descriptions is False
        assert loaded.show_archived is True
        assert loaded.confirm_archive is False
        assert loaded.default_priority == 3

    def test_save_creates_parent_dirs(self, tmp_path: Path):
        path = tmp_path / "nested" / "dir" / "tui.toml"
        save_config(TuiConfig(), path)
        assert path.exists()

    def test_load_partial_config(self, tmp_path: Path):
        path = tmp_path / "tui.toml"
        path.write_text('theme = "light"\n')
        config = load_config(path)
        assert config.theme == "light"
        assert config.default_priority == 1  # default preserved

    def test_save_format(self, tmp_path: Path):
        path = tmp_path / "tui.toml"
        save_config(TuiConfig(), path)
        text = path.read_text()
        assert 'theme = "dark"' in text
        assert "show_task_descriptions = true" in text
        assert "show_archived = false" in text
        assert "default_priority = 1" in text


# ---- TUI app + settings screen pilot tests ----


@pytest.fixture
def tui_db_path(tmp_path: Path) -> Path:
    return tmp_path / "tui-test.db"


class TestStickyNotesApp:
    async def test_app_mounts_with_injected_db(self, tui_db_path: Path):
        app = StickyNotesApp(db_path=tui_db_path)
        async with app.run_test() as pilot:
            assert app.db_path == tui_db_path
            assert tui_db_path.exists()
            assert hasattr(app, "conn")
            assert hasattr(app, "config")

    def test_app_default_db_path(self):
        app = StickyNotesApp()
        assert app.db_path == DEFAULT_DB_PATH

    async def test_dark_mode_from_config(self, tui_db_path: Path):
        app = StickyNotesApp(db_path=tui_db_path)
        async with app.run_test():
            assert app.dark is True


class TestSettingsScreen:
    async def test_settings_screen_mounts(self, tui_db_path: Path):
        app = StickyNotesApp(db_path=tui_db_path)
        async with app.run_test() as pilot:
            await pilot.press("s")
            await pilot.pause()
            assert isinstance(app.screen, SettingsScreen)

    async def test_db_path_displayed(self, tui_db_path: Path):
        app = StickyNotesApp(db_path=tui_db_path)
        async with app.run_test() as pilot:
            await pilot.press("s")
            await pilot.pause()
            db_path_widget = app.screen.query_one("#db-path", Static)
            assert str(tui_db_path) in str(db_path_widget.render())

    async def test_db_size_displayed(self, tui_db_path: Path):
        app = StickyNotesApp(db_path=tui_db_path)
        async with app.run_test() as pilot:
            await pilot.press("s")
            await pilot.pause()
            db_size_widget = app.screen.query_one("#db-size", Static)
            renderable = str(db_size_widget.render())
            assert "Size:" in renderable
            assert "KB" in renderable or "B" in renderable

    async def test_escape_pops_settings(self, tui_db_path: Path):
        app = StickyNotesApp(db_path=tui_db_path)
        async with app.run_test() as pilot:
            await pilot.press("s")
            await pilot.pause()
            assert isinstance(app.screen, SettingsScreen)
            await pilot.press("escape")
            await pilot.pause()
            assert not isinstance(app.screen, SettingsScreen)

    async def test_settings_uses_app_config(self, tui_db_path: Path):
        app = StickyNotesApp(db_path=tui_db_path)
        async with app.run_test() as pilot:
            await pilot.press("s")
            await pilot.pause()
            assert app.screen.typed_app.config is app.config
