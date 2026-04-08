from __future__ import annotations

from textual import events
from textual.containers import Horizontal, Vertical, ScrollableContainer
from textual.message import Message
from textual.widgets import Label

from sticky_notes.models import Status, Task
from sticky_notes.tui.markup import escape_markup
from sticky_notes.tui.model import WorkspaceModel
from sticky_notes.tui.widgets.task_card import TaskCard


class _KanbanScrollable(ScrollableContainer):
    can_focus = False


class KanbanBoard(Horizontal):
    _grid: list[list[TaskCard]] | None = None
    _status_names: dict[int, str] = {}

    class TaskActivated(Message):
        """A task card was activated on the kanban board."""

        def __init__(self, task: Task) -> None:
            self.task = task
            super().__init__()

    class TaskStatusMove(Message):
        """A task should be moved to a different status column."""

        def __init__(self, task: Task, new_status_id: int) -> None:
            self.task = task
            self.new_status_id = new_status_id
            super().__init__()

    def _build_column(self, status: Status, tasks: list[Task]) -> Vertical:
        title = f"({len(tasks)}) {escape_markup(status.name)}"
        cards = [TaskCard(t, classes="task-card") for t in tasks]
        return Vertical(
            Label(title, classes="status-col-title"),
            _KanbanScrollable(*cards),
            id=f"status-col-{status.id}",
            classes="status-col",
        )

    @staticmethod
    def _tasks_by_status(tasks: tuple[Task, ...]) -> dict[int, list[Task]]:
        by_status: dict[int, list[Task]] = {}
        for task in tasks:
            by_status.setdefault(task.status_id, []).append(task)
        return by_status

    async def load(self, model: WorkspaceModel) -> None:
        """Full teardown and rebuild — used for initial mount and workspace switch."""
        self._grid = None
        self._status_names = {s.id: s.name for s in model.statuses}
        await self.remove_children()
        by_status = self._tasks_by_status(model.all_tasks)
        for status in model.statuses:
            bucket = by_status.get(status.id, [])
            self.mount(self._build_column(status, bucket))

    async def sync(self, model: WorkspaceModel) -> None:
        """Diff-based update — moves/adds/removes cards without full teardown."""
        self._status_names = {s.id: s.name for s in model.statuses}
        by_status = self._tasks_by_status(model.all_tasks)

        existing_col_ids = {col.id for col in self.query(".status-col")}
        expected_col_ids = {f"status-col-{s.id}" for s in model.statuses}

        # Remove columns for deleted/archived statuses
        for col_id in existing_col_ids - expected_col_ids:
            await self.query_one(f"#{col_id}").remove()

        # Add or update columns
        for status in model.statuses:
            col_id = f"status-col-{status.id}"
            bucket = by_status.get(status.id, [])

            if col_id not in existing_col_ids:
                self.mount(self._build_column(status, bucket))
            else:
                col = self.query_one(f"#{col_id}")
                scrollable = col.query_one(_KanbanScrollable)
                await self._sync_cards(scrollable, bucket)
                self._update_col_title(col, len(bucket))

        self._grid = None

    async def _sync_cards(self, scrollable: _KanbanScrollable, expected: list[Task]) -> None:
        current_cards = {c.task_data.id: c for c in scrollable.query(TaskCard)}
        expected_ids = {t.id for t in expected}

        # Remove cards no longer in this column
        for task_id, card in current_cards.items():
            if task_id not in expected_ids:
                await card.remove()

        # Add new cards or update existing card data
        for task in expected:
            if task.id not in current_cards:
                await scrollable.mount(TaskCard(task, classes="task-card"))
            else:
                card = current_cards[task.id]
                card.task_data = task
                card.update(f"{task.id:d}: {escape_markup(task.title)}")

    def _update_col_title(self, col, count: int) -> None:
        status_id = int(col.id.removeprefix("status-col-"))
        name = escape_markup(self._status_names[status_id])
        col.query_one(".status-col-title", Label).update(f"({count}) {name}")

    def on_task_card_activated(self, event: TaskCard.Activated) -> None:
        event.stop()
        self.post_message(self.TaskActivated(event.task))

    # -- Grid navigation --

    def _build_grid(self) -> list[list[TaskCard]]:
        if self._grid is None:
            grid: list[list[TaskCard]] = []
            for col in self.query(".status-col"):
                cards = list(col.query(TaskCard))
                grid.append(cards)
            self._grid = grid
        return self._grid

    def _find_card_position(
        self, card: TaskCard, grid: list[list[TaskCard]]
    ) -> tuple[int, int] | None:
        for ci, column in enumerate(grid):
            for ri, c in enumerate(column):
                if c is card:
                    return (ci, ri)
        return None

    def _navigate(self, col_delta: int, row_delta: int) -> bool:
        focused = self.screen.focused
        if not isinstance(focused, TaskCard):
            return False
        grid = self._build_grid()
        non_empty = [i for i, col in enumerate(grid) if col]
        if not non_empty:
            return False
        pos = self._find_card_position(focused, grid)
        if pos is None:
            return False
        ci, ri = pos
        # Column movement: wrap around, skip empty columns
        if col_delta != 0:
            idx = non_empty.index(ci)
            idx = (idx + col_delta) % len(non_empty)
            new_ci = non_empty[idx]
            new_ri = min(ri, len(grid[new_ci]) - 1)
        # Row movement: wrap within column
        else:
            new_ci = ci
            new_ri = (ri + row_delta) % len(grid[ci])
        self.screen.set_focus(grid[new_ci][new_ri])
        return True

    def key_up(self, event: events.Key) -> None:
        if self._navigate(0, -1):
            event.stop()

    def key_down(self, event: events.Key) -> None:
        if self._navigate(0, 1):
            event.stop()

    def key_left(self, event: events.Key) -> None:
        if self._navigate(-1, 0):
            event.stop()

    def key_right(self, event: events.Key) -> None:
        if self._navigate(1, 0):
            event.stop()

    # ijkl aliases (home-row navigation)

    def key_i(self, event: events.Key) -> None:
        if self._navigate(0, -1):
            event.stop()

    def key_k(self, event: events.Key) -> None:
        if self._navigate(0, 1):
            event.stop()

    def key_j(self, event: events.Key) -> None:
        if self._navigate(-1, 0):
            event.stop()

    def key_l(self, event: events.Key) -> None:
        if self._navigate(1, 0):
            event.stop()

    # Status move (called by app-level bindings)

    def _move_status(self, delta: int) -> bool:
        focused = self.screen.focused
        if not isinstance(focused, TaskCard):
            return False
        cols = list(self.query(".status-col"))
        current_id = f"status-col-{focused.task_data.status_id}"
        ci = next((i for i, c in enumerate(cols) if c.id == current_id), None)
        if ci is None:
            return False
        new_ci = ci + delta
        if new_ci < 0 or new_ci >= len(cols):
            return False
        status_id = int(cols[new_ci].id.removeprefix("status-col-"))
        self.post_message(self.TaskStatusMove(focused.task_data, status_id))
        return True

