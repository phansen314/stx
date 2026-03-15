from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING, NamedTuple

from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import Static

from sticky_notes import service
from sticky_notes.active_board import get_active_board_id
from sticky_notes.models import Column, TaskFilter
from sticky_notes.service_models import TaskRef
from sticky_notes.tui.widgets.column_widget import ColumnWidget
from sticky_notes.tui.widgets.task_card import TaskCard

if TYPE_CHECKING:
    from sticky_notes.tui.app import StickyNotesApp


class Direction(StrEnum):
    UP = "up"
    DOWN = "down"
    LEFT = "left"
    RIGHT = "right"


class ColumnSlot(NamedTuple):
    column: Column
    tasks: tuple[TaskRef, ...]


class BoardView(Horizontal):
    DEFAULT_CSS = """
    BoardView {
        height: 1fr;
        width: 100%;
    }
    """

    BINDINGS = [
        Binding("n", "create_task", "New Task", show=False),
    ]

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._columns: list[ColumnSlot] = []
        self._col_idx: int = 0
        self._task_idx: int = 0
        self._pending_focus_task_id: int | None = None

    @property
    def _has_cards(self) -> bool:
        return any(slot.tasks for slot in self._columns)

    @property
    def typed_app(self) -> StickyNotesApp:
        return self.app  # type: ignore[return-value]

    @property
    def focused_position(self) -> tuple[int, int] | None:
        if not self._has_cards:
            return None
        return (self._col_idx, self._task_idx)

    def on_mount(self) -> None:
        self._load_board()

    def _load_board(self) -> None:
        conn = self.typed_app.conn
        db_path = self.typed_app.db_path
        config = self.typed_app.config

        board_id = get_active_board_id(db_path)
        if board_id is None:
            self._columns = []
            self.mount(Static("No active board", id="no-board-message"))
            return

        columns = service.list_columns(conn, board_id)
        if not columns:
            self._columns = []
            self.mount(Static("No columns on this board", id="no-columns-message"))
            return

        task_filter = TaskFilter(include_archived=config.show_archived)
        tasks = service.list_task_refs_filtered(
            conn, board_id, task_filter=task_filter
        )

        tasks_by_column: dict[int, list[TaskRef]] = {col.id: [] for col in columns}
        for task_ref in tasks:
            if task_ref.column_id in tasks_by_column:
                tasks_by_column[task_ref.column_id].append(task_ref)

        self._columns = [
            ColumnSlot(col, tuple(tasks_by_column[col.id])) for col in columns
        ]

        self._mount_from_model()

        self._col_idx = 0
        self._task_idx = 0
        if self._has_cards:
            if self._pending_focus_task_id is not None:
                self.call_after_refresh(self._restore_focus)
            else:
                self.call_after_refresh(self._focus_current)

    def _mount_from_model(self) -> None:
        self.mount(
            *[ColumnWidget(slot.column, slot.tasks) for slot in self._columns]
        )

    def on_task_card_navigate(self, message: TaskCard.Navigate) -> None:
        message.stop()
        match Direction(message.direction):
            case Direction.UP:
                self._cursor_up()
            case Direction.DOWN:
                self._cursor_down()
            case Direction.LEFT:
                self._cursor_left()
            case Direction.RIGHT:
                self._cursor_right()

    def _get_columns(self) -> list[ColumnWidget]:
        return list(self.query(ColumnWidget))

    def _get_cards(self, col: ColumnWidget) -> list[TaskCard]:
        return list(col.query(TaskCard))

    def _focus_current(self) -> None:
        if not self._columns:
            return
        self._col_idx = min(self._col_idx, len(self._columns) - 1)
        tasks = self._columns[self._col_idx].tasks
        if not tasks:
            return
        self._task_idx = min(self._task_idx, len(tasks) - 1)
        columns = self._get_columns()
        self._get_cards(columns[self._col_idx])[self._task_idx].focus()

    def _cursor_up(self) -> None:
        if not self._columns:
            return
        if self._task_idx > 0:
            self._task_idx -= 1
            self._focus_current()

    def _cursor_down(self) -> None:
        if not self._columns:
            return
        if self._task_idx < len(self._columns[self._col_idx].tasks) - 1:
            self._task_idx += 1
            self._focus_current()

    def _cursor_left(self) -> None:
        if not self._columns:
            return
        for candidate in range(self._col_idx - 1, -1, -1):
            if self._columns[candidate].tasks:
                self._col_idx = candidate
                self._task_idx = min(self._task_idx, len(self._columns[candidate].tasks) - 1)
                self._focus_current()
                return

    def _cursor_right(self) -> None:
        if not self._columns:
            return
        for candidate in range(self._col_idx + 1, len(self._columns)):
            if self._columns[candidate].tasks:
                self._col_idx = candidate
                self._task_idx = min(self._task_idx, len(self._columns[candidate].tasks) - 1)
                self._focus_current()
                return

    def on_task_card_move_request(self, message: TaskCard.MoveRequest) -> None:
        message.stop()
        match Direction(message.direction):
            case Direction.LEFT:
                self.run_worker(self._move_task(-1))
            case Direction.RIGHT:
                self.run_worker(self._move_task(1))

    async def reload(self, focus_task_id: int | None = None) -> None:
        self._pending_focus_task_id = focus_task_id
        await self.remove_children()
        self._load_board()

    async def _move_task(self, delta: int) -> None:
        if not self._columns:
            return

        target_col_idx = self._col_idx + delta
        if target_col_idx < 0 or target_col_idx >= len(self._columns):
            return

        source_tasks = self._columns[self._col_idx].tasks
        if not source_tasks:
            return

        task_id = source_tasks[self._task_idx].id
        target_column_id = self._columns[target_col_idx].column.id
        position = len(self._columns[target_col_idx].tasks)

        conn = self.typed_app.conn
        service.move_task(conn, task_id, target_column_id, position, "tui")

        await self.reload(focus_task_id=task_id)

    def _restore_focus(self) -> None:
        for col_idx, slot in enumerate(self._columns):
            for task_idx, task_ref in enumerate(slot.tasks):
                if task_ref.id == self._pending_focus_task_id:
                    self._col_idx = col_idx
                    self._task_idx = task_idx
                    self._pending_focus_task_id = None
                    self._focus_current()
                    return
        # Fallback: task not found, focus current position
        self._pending_focus_task_id = None
        self._focus_current()

    def on_task_card_show_request(self, message: TaskCard.ShowRequest) -> None:
        message.stop()
        from sticky_notes.tui.screens.task_detail import TaskDetailModal

        self.typed_app.push_screen(
            TaskDetailModal(message.task_id),
            callback=self._handle_detail_dismiss,
        )

    def _handle_detail_dismiss(self, result: int | None) -> None:
        if result is not None:
            # result is a task_id — user pressed 'e' to edit
            self._open_edit(result)

    def _open_edit(self, task_id: int) -> None:
        """Open the edit modal for a task. Wired up in Phase 5."""
        pass

    def on_task_card_archive_request(self, message: TaskCard.ArchiveRequest) -> None:
        message.stop()
        task_id = message.task_id
        if self.typed_app.config.confirm_archive:
            from sticky_notes.tui.screens.confirm_dialog import ConfirmDialog

            self.typed_app.push_screen(
                ConfirmDialog(f"Archive task-{task_id:04d}?"),
                callback=lambda ok, tid=task_id: self._handle_archive_confirm(tid, ok),
            )
        else:
            self.run_worker(self._archive_and_reload(task_id))

    def _handle_archive_confirm(self, task_id: int, confirmed: bool) -> None:
        if confirmed:
            self.run_worker(self._archive_and_reload(task_id))

    async def _archive_and_reload(self, task_id: int) -> None:
        service.update_task(self.typed_app.conn, task_id, {"archived": True}, "tui")
        # Find the next task to focus: prefer same position in same column,
        # clamping down if we archived the last task in the column.
        col_tasks = self._columns[self._col_idx].tasks
        remaining = [t for t in col_tasks if t.id != task_id]
        if remaining:
            # Clamp to last task if we were at the end
            idx = min(self._task_idx, len(remaining) - 1)
            await self.reload(focus_task_id=remaining[idx].id)
        else:
            await self.reload()
