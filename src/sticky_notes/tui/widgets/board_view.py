from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING, NamedTuple

from textual.binding import Binding
from textual.containers import Horizontal
from textual.widgets import Static

from sticky_notes import service
from sticky_notes.active_board import get_active_board_id, set_active_board_id
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
    can_focus = True

    DEFAULT_CSS = """
    BoardView {
        height: 1fr;
        width: 100%;
    }
    """

    BINDINGS = [
        Binding("n", "create_task", "New Task"),
        Binding("b", "select_board", "Switch Board"),
        Binding("p", "select_project", "Filter Project"),
        Binding("a", "all_tasks", "All Tasks"),
    ]

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._columns: list[ColumnSlot] = []
        self._col_idx: int = 0
        self._task_idx: int = 0
        self._pending_focus_task_id: int | None = None
        self._board_id: int | None = None
        self._project_filter_id: int | None = None

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

        self._board_id = get_active_board_id(db_path)
        if self._board_id is None:
            self._columns = []
            self.mount(Static("No active board", id="no-board-message"))
            return

        columns = service.list_columns(conn, self._board_id)
        if not columns:
            self._columns = []
            self.mount(Static("No columns on this board", id="no-columns-message"))
            return

        task_filter = TaskFilter(
            include_archived=config.show_archived,
            project_id=self._project_filter_id,
        )
        tasks = service.list_task_refs_filtered(
            conn, self._board_id, task_filter=task_filter
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
        else:
            self.call_after_refresh(self.focus)

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
        # If current column is empty, search for first non-empty column
        if not self._columns[self._col_idx].tasks:
            found = False
            for candidate in range(self._col_idx + 1, len(self._columns)):
                if self._columns[candidate].tasks:
                    self._col_idx = candidate
                    found = True
                    break
            if not found:
                for candidate in range(self._col_idx - 1, -1, -1):
                    if self._columns[candidate].tasks:
                        self._col_idx = candidate
                        found = True
                        break
            if not found:
                self.focus()
                return
        tasks = self._columns[self._col_idx].tasks
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

    def action_create_task(self) -> None:
        if not self._columns:
            return
        from sticky_notes.tui.screens.task_form import TaskFormModal

        col = self._columns[self._col_idx].column
        self.typed_app.push_screen(
            TaskFormModal(
                self.typed_app.conn,
                self._board_id,
                mode="create",
                column_id=col.id,
                default_priority=self.typed_app.config.default_priority,
            ),
            callback=self._handle_create,
        )

    def _handle_create(self, result: dict | None) -> None:
        if result is None:
            return
        task = service.create_task(
            self.typed_app.conn,
            board_id=self._board_id,
            title=result["title"],
            column_id=result["column_id"],
            description=result.get("description"),
            priority=result.get("priority", 1),
            due_date=result.get("due_date"),
            project_id=result.get("project_id"),
        )
        self.run_worker(self.reload(focus_task_id=task.id))

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

    def on_task_card_edit_request(self, message: TaskCard.EditRequest) -> None:
        message.stop()
        self._open_edit(message.task_id)

    def _open_edit(self, task_id: int) -> None:
        from sticky_notes.tui.screens.task_form import TaskFormModal

        task = service.get_task(self.typed_app.conn, task_id)
        defaults = {
            "title": task.title,
            "description": task.description,
            "priority": task.priority,
            "due_date": task.due_date,
            "project_id": task.project_id,
        }
        self.typed_app.push_screen(
            TaskFormModal(
                self.typed_app.conn,
                self._board_id,
                mode="edit",
                defaults=defaults,
                default_priority=self.typed_app.config.default_priority,
            ),
            callback=lambda r, tid=task_id: self._handle_edit(tid, r),
        )

    def _handle_edit(self, task_id: int, result: dict | None) -> None:
        if result is None:
            return
        # Diff against current values to build a minimal changes dict
        task = service.get_task(self.typed_app.conn, task_id)
        current = {
            "title": task.title,
            "description": task.description,
            "priority": task.priority,
            "due_date": task.due_date,
            "project_id": task.project_id,
        }
        changes = {k: v for k, v in result.items() if current.get(k) != v}
        if changes:
            service.update_task(self.typed_app.conn, task_id, changes, "tui")
        self.run_worker(self.reload(focus_task_id=task_id))

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

    def action_select_board(self) -> None:
        from sticky_notes.tui.screens.board_select import BoardSelectModal

        self.typed_app.push_screen(
            BoardSelectModal(self.typed_app.conn, self._board_id),
            callback=self._handle_board_select,
        )

    def _handle_board_select(self, result: int | None) -> None:
        if result is None or result == self._board_id:
            return
        set_active_board_id(self.typed_app.db_path, result)
        self._project_filter_id = None  # reset project filter on board switch
        self.run_worker(self.reload())

    def action_select_project(self) -> None:
        if self._board_id is None:
            return
        from sticky_notes.tui.screens.project_select import (
            ProjectSelectModal,
            _CANCEL_SENTINEL,
        )

        self._cancel_sentinel = _CANCEL_SENTINEL
        self.typed_app.push_screen(
            ProjectSelectModal(
                self.typed_app.conn,
                self._board_id,
                self._project_filter_id,
            ),
            callback=self._handle_project_select,
        )

    def _handle_project_select(self, result: int) -> None:
        if result == self._cancel_sentinel:
            return
        new_filter = result if result != 0 else None
        if new_filter == self._project_filter_id:
            return
        self._project_filter_id = new_filter
        self.run_worker(self.reload())

    def action_all_tasks(self) -> None:
        if self._board_id is None:
            return
        from sticky_notes.tui.screens.all_tasks import AllTasksScreen

        self.typed_app.push_screen(AllTasksScreen())
