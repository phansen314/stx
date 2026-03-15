from __future__ import annotations

from pathlib import Path

import pytest

from sticky_notes import service
from sticky_notes.connection import DEFAULT_DB_PATH
from sticky_notes.tui.app import StickyNotesApp
from sticky_notes.tui.config import TuiConfig, load_config, save_config
from sticky_notes.tui.screens.confirm_dialog import ConfirmDialog
from sticky_notes.tui.screens.settings import SettingsScreen
from sticky_notes.tui.screens.task_detail import TaskDetailModal
from sticky_notes.tui.widgets import BoardView, ColumnWidget, TaskCard
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


# ---- Board view tests ----


class TestBoardView:
    async def test_seeded_board_renders_three_columns(
        self, seeded_tui_db: tuple[Path, dict]
    ):
        db_path, ids = seeded_tui_db
        app = StickyNotesApp(db_path=db_path)
        async with app.run_test():
            columns = app.query(ColumnWidget)
            assert len(columns) == 3

    async def test_seeded_board_renders_eight_task_cards(
        self, seeded_tui_db: tuple[Path, dict]
    ):
        db_path, ids = seeded_tui_db
        app = StickyNotesApp(db_path=db_path)
        async with app.run_test():
            cards = app.query(TaskCard)
            assert len(cards) == 8

    async def test_column_headers_contain_names(
        self, seeded_tui_db: tuple[Path, dict]
    ):
        db_path, ids = seeded_tui_db
        app = StickyNotesApp(db_path=db_path)
        async with app.run_test():
            headers = app.query(".column-header")
            header_texts = [str(h.render()) for h in headers]
            assert any("Todo" in t for t in header_texts)
            assert any("In Progress" in t for t in header_texts)
            assert any("Done" in t for t in header_texts)

    async def test_empty_db_shows_no_board_message(self, tui_db_path: Path):
        app = StickyNotesApp(db_path=tui_db_path)
        async with app.run_test():
            msg = app.query_one("#no-board-message", Static)
            assert "No active board" in str(msg.render())

    async def test_task_cards_contain_expected_text(
        self, seeded_tui_db: tuple[Path, dict]
    ):
        db_path, ids = seeded_tui_db
        app = StickyNotesApp(db_path=db_path)
        async with app.run_test():
            cards = app.query(TaskCard)
            texts = [str(c.render()) for c in cards]
            assert any("task-" in t for t in texts)
            assert any("[P" in t for t in texts)

    async def test_archived_task_hidden_by_default(
        self, seeded_tui_db: tuple[Path, dict]
    ):
        db_path, ids = seeded_tui_db
        # Archive one task
        from sticky_notes.connection import get_connection

        conn = get_connection(db_path)
        service.update_task(
            conn, ids["task_ids"]["scaffold"], {"archived": True}, "test"
        )
        conn.close()

        app = StickyNotesApp(db_path=db_path)
        async with app.run_test():
            cards = app.query(TaskCard)
            assert len(cards) == 7


# ---- Board view test helpers ----


async def _wait_for_board(pilot) -> None:
    """Wait for board to mount and initial focus to be set."""
    await pilot.pause()


def _board(app: StickyNotesApp) -> BoardView:
    return app.query_one(BoardView)


# ---- Board navigation tests ----


class TestBoardNavigation:
    """Keyboard navigation across the 2D grid of columns and task cards."""

    async def test_initial_focus_on_first_card(
        self, seeded_tui_db: tuple[Path, dict]
    ):
        db_path, ids = seeded_tui_db
        app = StickyNotesApp(db_path=db_path)
        async with app.run_test() as pilot:
            await _wait_for_board(pilot)
            assert _board(app).focused_position == (0, 0)
            assert isinstance(app.focused, TaskCard)

    async def test_down_arrow_moves_to_next_card(
        self, seeded_tui_db: tuple[Path, dict]
    ):
        db_path, ids = seeded_tui_db
        app = StickyNotesApp(db_path=db_path)
        async with app.run_test() as pilot:
            await _wait_for_board(pilot)
            await pilot.press("down")
            await pilot.pause()
            assert _board(app).focused_position == (0, 1)

    async def test_up_arrow_moves_to_previous_card(
        self, seeded_tui_db: tuple[Path, dict]
    ):
        db_path, ids = seeded_tui_db
        app = StickyNotesApp(db_path=db_path)
        async with app.run_test() as pilot:
            await _wait_for_board(pilot)
            await pilot.press("down")
            await pilot.pause()
            await pilot.press("up")
            await pilot.pause()
            assert _board(app).focused_position == (0, 0)

    async def test_up_at_top_stays_clamped(
        self, seeded_tui_db: tuple[Path, dict]
    ):
        db_path, ids = seeded_tui_db
        app = StickyNotesApp(db_path=db_path)
        async with app.run_test() as pilot:
            await _wait_for_board(pilot)
            await pilot.press("up")
            await pilot.pause()
            assert _board(app).focused_position == (0, 0)

    async def test_down_at_bottom_stays_clamped(
        self, seeded_tui_db: tuple[Path, dict]
    ):
        db_path, ids = seeded_tui_db
        app = StickyNotesApp(db_path=db_path)
        async with app.run_test() as pilot:
            await _wait_for_board(pilot)
            # Todo column has 4 tasks, go to the bottom
            await pilot.press("down", "down", "down")
            await pilot.pause()
            assert _board(app).focused_position == (0, 3)
            # One more down should stay at bottom
            await pilot.press("down")
            await pilot.pause()
            assert _board(app).focused_position == (0, 3)

    async def test_right_arrow_moves_to_next_column(
        self, seeded_tui_db: tuple[Path, dict]
    ):
        db_path, ids = seeded_tui_db
        app = StickyNotesApp(db_path=db_path)
        async with app.run_test() as pilot:
            await _wait_for_board(pilot)
            await pilot.press("right")
            await pilot.pause()
            assert _board(app).focused_position == (1, 0)

    async def test_left_arrow_moves_to_previous_column(
        self, seeded_tui_db: tuple[Path, dict]
    ):
        db_path, ids = seeded_tui_db
        app = StickyNotesApp(db_path=db_path)
        async with app.run_test() as pilot:
            await _wait_for_board(pilot)
            await pilot.press("right")
            await pilot.pause()
            await pilot.press("left")
            await pilot.pause()
            assert _board(app).focused_position == (0, 0)

    async def test_left_at_first_column_stays(
        self, seeded_tui_db: tuple[Path, dict]
    ):
        db_path, ids = seeded_tui_db
        app = StickyNotesApp(db_path=db_path)
        async with app.run_test() as pilot:
            await _wait_for_board(pilot)
            await pilot.press("left")
            await pilot.pause()
            assert _board(app).focused_position == (0, 0)

    async def test_right_at_last_column_stays(
        self, seeded_tui_db: tuple[Path, dict]
    ):
        db_path, ids = seeded_tui_db
        app = StickyNotesApp(db_path=db_path)
        async with app.run_test() as pilot:
            await _wait_for_board(pilot)
            # Move to last column (Done, col 2)
            await pilot.press("right", "right")
            await pilot.pause()
            pos = _board(app).focused_position
            assert pos is not None and pos[0] == 2
            # One more right should stay
            await pilot.press("right")
            await pilot.pause()
            assert _board(app).focused_position == pos

    async def test_vertical_position_clamped_on_column_switch(
        self, seeded_tui_db: tuple[Path, dict]
    ):
        db_path, ids = seeded_tui_db
        app = StickyNotesApp(db_path=db_path)
        async with app.run_test() as pilot:
            await _wait_for_board(pilot)
            # Go to task index 3 in Todo (4 tasks: 0,1,2,3)
            await pilot.press("down", "down", "down")
            await pilot.pause()
            assert _board(app).focused_position == (0, 3)
            # Move right to In Progress (only 2 tasks: 0,1)
            await pilot.press("right")
            await pilot.pause()
            assert _board(app).focused_position == (1, 1)  # clamped

    async def test_focused_card_has_focus_property(
        self, seeded_tui_db: tuple[Path, dict]
    ):
        db_path, ids = seeded_tui_db
        app = StickyNotesApp(db_path=db_path)
        async with app.run_test() as pilot:
            await _wait_for_board(pilot)
            focused = app.focused
            assert isinstance(focused, TaskCard)
            assert focused.has_focus

    async def test_right_skips_empty_column(
        self, seeded_tui_db_empty_middle: tuple[Path, dict]
    ):
        db_path, ids = seeded_tui_db_empty_middle
        app = StickyNotesApp(db_path=db_path)
        async with app.run_test() as pilot:
            await _wait_for_board(pilot)
            assert _board(app).focused_position == (0, 0)
            # Right should skip empty In Progress (col 1) -> Done (col 2)
            await pilot.press("right")
            await pilot.pause()
            assert _board(app).focused_position == (2, 0)

    async def test_left_skips_empty_column(
        self, seeded_tui_db_empty_middle: tuple[Path, dict]
    ):
        db_path, ids = seeded_tui_db_empty_middle
        app = StickyNotesApp(db_path=db_path)
        async with app.run_test() as pilot:
            await _wait_for_board(pilot)
            # Navigate to Done (col 2) — skips empty col 1
            await pilot.press("right")
            await pilot.pause()
            assert _board(app).focused_position == (2, 0)
            # Left should skip empty In Progress (col 1) -> Todo (col 0)
            await pilot.press("left")
            await pilot.pause()
            assert _board(app).focused_position == (0, 0)


# ---- Board task movement tests ----


class TestBoardTaskMovement:
    """Shift+Arrow moves focused task to adjacent column."""

    async def test_shift_right_moves_task_to_next_column(
        self, seeded_tui_db: tuple[Path, dict]
    ):
        db_path, ids = seeded_tui_db
        app = StickyNotesApp(db_path=db_path)
        async with app.run_test() as pilot:
            await _wait_for_board(pilot)
            # Focus is at (0, 0) in Todo. Shift+right moves to In Progress.
            await pilot.press("shift+right")
            await pilot.pause()
            await pilot.pause()
            board = _board(app)
            assert board.focused_position is not None
            assert board.focused_position[0] == 1
            columns = board._get_columns()
            todo_cards = board._get_cards(columns[0])
            in_progress_cards = board._get_cards(columns[1])
            assert len(todo_cards) == 3
            assert len(in_progress_cards) == 3

    async def test_shift_left_moves_task_to_previous_column(
        self, seeded_tui_db: tuple[Path, dict]
    ):
        db_path, ids = seeded_tui_db
        app = StickyNotesApp(db_path=db_path)
        async with app.run_test() as pilot:
            await _wait_for_board(pilot)
            # Navigate to In Progress first
            await pilot.press("right")
            await pilot.pause()
            assert _board(app).focused_position == (1, 0)
            # Move task left to Todo
            await pilot.press("shift+left")
            await pilot.pause()
            await pilot.pause()
            board = _board(app)
            assert board.focused_position is not None
            assert board.focused_position[0] == 0
            columns = board._get_columns()
            todo_cards = board._get_cards(columns[0])
            in_progress_cards = board._get_cards(columns[1])
            assert len(todo_cards) == 5
            assert len(in_progress_cards) == 1

    async def test_shift_left_at_first_column_is_noop(
        self, seeded_tui_db: tuple[Path, dict]
    ):
        db_path, ids = seeded_tui_db
        app = StickyNotesApp(db_path=db_path)
        async with app.run_test() as pilot:
            await _wait_for_board(pilot)
            assert _board(app).focused_position == (0, 0)
            await pilot.press("shift+left")
            await pilot.pause()
            await pilot.pause()
            assert _board(app).focused_position == (0, 0)
            columns = _board(app)._get_columns()
            assert len(_board(app)._get_cards(columns[0])) == 4

    async def test_shift_right_at_last_column_is_noop(
        self, seeded_tui_db: tuple[Path, dict]
    ):
        db_path, ids = seeded_tui_db
        app = StickyNotesApp(db_path=db_path)
        async with app.run_test() as pilot:
            await _wait_for_board(pilot)
            # Navigate to Done (col 2)
            await pilot.press("right", "right")
            await pilot.pause()
            pos = _board(app).focused_position
            assert pos is not None and pos[0] == 2
            await pilot.press("shift+right")
            await pilot.pause()
            await pilot.pause()
            assert _board(app).focused_position == pos

    async def test_move_preserves_focus_on_moved_task(
        self, seeded_tui_db: tuple[Path, dict]
    ):
        db_path, ids = seeded_tui_db
        app = StickyNotesApp(db_path=db_path)
        async with app.run_test() as pilot:
            await _wait_for_board(pilot)
            focused = app.focused
            assert isinstance(focused, TaskCard)
            task_id_before = focused.task_ref.id
            await pilot.press("shift+right")
            await pilot.pause()
            await pilot.pause()
            focused_after = app.focused
            assert isinstance(focused_after, TaskCard)
            assert focused_after.task_ref.id == task_id_before

    async def test_move_last_task_empties_column(
        self, seeded_tui_db: tuple[Path, dict]
    ):
        db_path, ids = seeded_tui_db
        app = StickyNotesApp(db_path=db_path)
        async with app.run_test() as pilot:
            await _wait_for_board(pilot)
            # Navigate to In Progress (2 tasks)
            await pilot.press("right")
            await pilot.pause()
            assert _board(app).focused_position == (1, 0)
            # Move first task right to Done
            await pilot.press("shift+right")
            await pilot.pause()
            await pilot.pause()
            # After rebuild, focus is on the moved task in Done.
            # Navigate left to get back to In Progress remaining task
            await pilot.press("left")
            await pilot.pause()
            board = _board(app)
            assert board.focused_position == (1, 0)
            columns = board._get_columns()
            in_progress_cards = board._get_cards(columns[1])
            assert len(in_progress_cards) == 1
            # Move that last task right too
            await pilot.press("shift+right")
            await pilot.pause()
            await pilot.pause()
            columns = _board(app)._get_columns()
            assert len(_board(app)._get_cards(columns[1])) == 0

    async def test_move_updates_database(
        self, seeded_tui_db: tuple[Path, dict]
    ):
        db_path, ids = seeded_tui_db
        app = StickyNotesApp(db_path=db_path)
        async with app.run_test() as pilot:
            await _wait_for_board(pilot)
            focused = app.focused
            assert isinstance(focused, TaskCard)
            task_id = focused.task_ref.id
            original_col = focused.task_ref.column_id
            await pilot.press("shift+right")
            await pilot.pause()
            await pilot.pause()
            # Verify in DB with a fresh connection
            from sticky_notes.connection import get_connection

            fresh_conn = get_connection(db_path)
            task = service.get_task(fresh_conn, task_id)
            fresh_conn.close()
            assert task.column_id != original_col
            assert task.column_id == ids["column_ids"]["in_progress"]

    async def test_move_to_adjacent_empty_column(
        self, seeded_tui_db_empty_middle: tuple[Path, dict]
    ):
        db_path, ids = seeded_tui_db_empty_middle
        app = StickyNotesApp(db_path=db_path)
        async with app.run_test() as pilot:
            await _wait_for_board(pilot)
            assert _board(app).focused_position == (0, 0)
            # Shift+right should move to col 1 (empty In Progress), NOT skip to col 2
            await pilot.press("shift+right")
            await pilot.pause()
            await pilot.pause()
            board = _board(app)
            assert board.focused_position is not None
            assert board.focused_position[0] == 1
            columns = board._get_columns()
            assert len(board._get_cards(columns[1])) == 1


# ---- Archive tests ----


class TestArchiveTask:
    """Pressing 'd' archives the focused task."""

    async def test_archive_with_confirm_yes(
        self, seeded_tui_db: tuple[Path, dict]
    ):
        db_path, ids = seeded_tui_db
        app = StickyNotesApp(db_path=db_path)
        async with app.run_test() as pilot:
            await _wait_for_board(pilot)
            assert len(app.query(TaskCard)) == 8
            # Press d to archive — confirm dialog should appear
            await pilot.press("d")
            await pilot.pause()
            assert isinstance(app.screen, ConfirmDialog)
            # Confirm with y
            await pilot.press("y")
            await pilot.pause()
            await pilot.pause()
            assert not isinstance(app.screen, ConfirmDialog)
            assert len(app.query(TaskCard)) == 7

    async def test_archive_with_confirm_no(
        self, seeded_tui_db: tuple[Path, dict]
    ):
        db_path, ids = seeded_tui_db
        app = StickyNotesApp(db_path=db_path)
        async with app.run_test() as pilot:
            await _wait_for_board(pilot)
            assert len(app.query(TaskCard)) == 8
            await pilot.press("d")
            await pilot.pause()
            assert isinstance(app.screen, ConfirmDialog)
            # Cancel with n
            await pilot.press("n")
            await pilot.pause()
            assert not isinstance(app.screen, ConfirmDialog)
            # No task removed
            assert len(app.query(TaskCard)) == 8

    async def test_archive_with_confirm_escape(
        self, seeded_tui_db: tuple[Path, dict]
    ):
        db_path, ids = seeded_tui_db
        app = StickyNotesApp(db_path=db_path)
        async with app.run_test() as pilot:
            await _wait_for_board(pilot)
            await pilot.press("d")
            await pilot.pause()
            assert isinstance(app.screen, ConfirmDialog)
            await pilot.press("escape")
            await pilot.pause()
            assert not isinstance(app.screen, ConfirmDialog)
            assert len(app.query(TaskCard)) == 8

    async def test_archive_without_confirm(
        self, seeded_tui_db: tuple[Path, dict]
    ):
        db_path, ids = seeded_tui_db
        app = StickyNotesApp(db_path=db_path)
        app.config.confirm_archive = False
        async with app.run_test() as pilot:
            await _wait_for_board(pilot)
            assert len(app.query(TaskCard)) == 8
            await pilot.press("d")
            await pilot.pause()
            await pilot.pause()
            # No dialog, straight to archive
            assert not isinstance(app.screen, ConfirmDialog)
            assert len(app.query(TaskCard)) == 7

    async def test_archive_updates_database(
        self, seeded_tui_db: tuple[Path, dict]
    ):
        db_path, ids = seeded_tui_db
        app = StickyNotesApp(db_path=db_path)
        app.config.confirm_archive = False
        async with app.run_test() as pilot:
            await _wait_for_board(pilot)
            focused = app.focused
            assert isinstance(focused, TaskCard)
            task_id = focused.task_ref.id
            await pilot.press("d")
            await pilot.pause()
            await pilot.pause()
            # Verify in DB
            from sticky_notes.connection import get_connection

            fresh_conn = get_connection(db_path)
            task = service.get_task(fresh_conn, task_id)
            fresh_conn.close()
            assert task.archived is True

    async def test_archive_via_delete_key(
        self, seeded_tui_db: tuple[Path, dict]
    ):
        db_path, ids = seeded_tui_db
        app = StickyNotesApp(db_path=db_path)
        app.config.confirm_archive = False
        async with app.run_test() as pilot:
            await _wait_for_board(pilot)
            assert len(app.query(TaskCard)) == 8
            await pilot.press("delete")
            await pilot.pause()
            await pilot.pause()
            assert len(app.query(TaskCard)) == 7

    async def test_archive_cursor_stays_in_same_column(
        self, seeded_tui_db: tuple[Path, dict]
    ):
        """After archiving, cursor should stay in the same column, not jump to (0,0)."""
        db_path, ids = seeded_tui_db
        app = StickyNotesApp(db_path=db_path)
        app.config.confirm_archive = False
        async with app.run_test() as pilot:
            await _wait_for_board(pilot)
            # Navigate to In Progress (col 1), task 0
            await pilot.press("right")
            await pilot.pause()
            assert _board(app).focused_position == (1, 0)
            # Archive it
            await pilot.press("d")
            await pilot.pause()
            await pilot.pause()
            # Should stay in col 1, not jump to (0, 0)
            board = _board(app)
            assert board.focused_position is not None
            assert board.focused_position[0] == 1
            assert board.focused_position[1] == 0

    async def test_archive_last_in_column_clamps_index(
        self, seeded_tui_db: tuple[Path, dict]
    ):
        """Archiving the last task in a column should clamp cursor up."""
        db_path, ids = seeded_tui_db
        app = StickyNotesApp(db_path=db_path)
        app.config.confirm_archive = False
        async with app.run_test() as pilot:
            await _wait_for_board(pilot)
            # Navigate to In Progress (col 1), go to last task (index 1)
            await pilot.press("right")
            await pilot.pause()
            await pilot.press("down")
            await pilot.pause()
            assert _board(app).focused_position == (1, 1)
            # Archive task at index 1 — only 1 task remains, cursor should clamp to 0
            await pilot.press("d")
            await pilot.pause()
            await pilot.pause()
            board = _board(app)
            assert board.focused_position is not None
            assert board.focused_position[0] == 1
            assert board.focused_position[1] == 0


# ---- Task detail modal tests ----


class TestTaskDetailModal:
    """Pressing 'enter' opens a read-only task detail modal."""

    async def test_enter_opens_detail_modal(
        self, seeded_tui_db: tuple[Path, dict]
    ):
        db_path, ids = seeded_tui_db
        app = StickyNotesApp(db_path=db_path)
        async with app.run_test() as pilot:
            await _wait_for_board(pilot)
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, TaskDetailModal)

    async def test_detail_shows_task_number_and_title(
        self, seeded_tui_db: tuple[Path, dict]
    ):
        db_path, ids = seeded_tui_db
        app = StickyNotesApp(db_path=db_path)
        async with app.run_test() as pilot:
            await _wait_for_board(pilot)
            focused = app.focused
            assert isinstance(focused, TaskCard)
            task_id = focused.task_ref.id
            task_title = focused.task_ref.title
            await pilot.press("enter")
            await pilot.pause()
            title_widget = app.screen.query_one("#detail-title", Static)
            rendered = str(title_widget.render())
            assert f"task-{task_id:04d}" in rendered
            assert task_title in rendered

    async def test_detail_shows_column_name(
        self, seeded_tui_db: tuple[Path, dict]
    ):
        db_path, ids = seeded_tui_db
        app = StickyNotesApp(db_path=db_path)
        async with app.run_test() as pilot:
            await _wait_for_board(pilot)
            await pilot.press("enter")
            await pilot.pause()
            texts = [str(w.render()) for w in app.screen.query(Static)]
            assert any("Todo" in t for t in texts)

    async def test_detail_shows_priority(
        self, seeded_tui_db: tuple[Path, dict]
    ):
        db_path, ids = seeded_tui_db
        app = StickyNotesApp(db_path=db_path)
        async with app.run_test() as pilot:
            await _wait_for_board(pilot)
            await pilot.press("enter")
            await pilot.pause()
            texts = [str(w.render()) for w in app.screen.query(Static)]
            assert any("Priority:" in t for t in texts)

    async def test_detail_shows_description(
        self, seeded_tui_db: tuple[Path, dict]
    ):
        db_path, ids = seeded_tui_db
        app = StickyNotesApp(db_path=db_path)
        async with app.run_test() as pilot:
            await _wait_for_board(pilot)
            # First task "Design API schema" has a description
            await pilot.press("enter")
            await pilot.pause()
            texts = [str(w.render()) for w in app.screen.query(Static)]
            assert any("Description" in t for t in texts)
            assert any("OpenAPI" in t for t in texts)

    async def test_detail_shows_dependencies(
        self, seeded_tui_db: tuple[Path, dict]
    ):
        db_path, ids = seeded_tui_db
        app = StickyNotesApp(db_path=db_path)
        async with app.run_test() as pilot:
            await _wait_for_board(pilot)
            # Navigate to "User CRUD" which is blocked by "Auth middleware"
            await pilot.press("down", "down")
            await pilot.pause()
            focused = app.focused
            assert isinstance(focused, TaskCard)
            assert focused.task_ref.title == "User CRUD"
            await pilot.press("enter")
            await pilot.pause()
            texts = [str(w.render()) for w in app.screen.query(Static)]
            assert any("Blocked by:" in t for t in texts)

    async def test_escape_dismisses_detail(
        self, seeded_tui_db: tuple[Path, dict]
    ):
        db_path, ids = seeded_tui_db
        app = StickyNotesApp(db_path=db_path)
        async with app.run_test() as pilot:
            await _wait_for_board(pilot)
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, TaskDetailModal)
            await pilot.press("escape")
            await pilot.pause()
            assert not isinstance(app.screen, TaskDetailModal)

    async def test_e_from_detail_dismisses_with_task_id(
        self, seeded_tui_db: tuple[Path, dict]
    ):
        db_path, ids = seeded_tui_db
        app = StickyNotesApp(db_path=db_path)
        async with app.run_test() as pilot:
            await _wait_for_board(pilot)
            await pilot.press("enter")
            await pilot.pause()
            assert isinstance(app.screen, TaskDetailModal)
            await pilot.press("e")
            await pilot.pause()
            # Detail should dismiss (edit modal not yet wired)
            assert not isinstance(app.screen, TaskDetailModal)
