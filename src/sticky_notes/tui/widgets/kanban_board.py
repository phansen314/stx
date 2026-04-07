from __future__ import annotations

from textual import events
from textual.containers import Horizontal, Vertical, ScrollableContainer
from textual.message import Message
from textual.widgets import Label

from sticky_notes.models import Task
from sticky_notes.tui.markup import escape_markup
from sticky_notes.tui.model import WorkspaceModel
from sticky_notes.tui.widgets.task_card import TaskCard


class _KanbanScrollable(ScrollableContainer):
    can_focus = False


class KanbanBoard(Horizontal):
    _grid: list[list[TaskCard]] | None = None

    class TaskActivated(Message):
        """A task card was activated on the kanban board."""

        def __init__(self, task: Task) -> None:
            self.task = task
            super().__init__()

    async def load(self, model: WorkspaceModel) -> None:
        self._grid = None
        await self.remove_children()
        all_tasks = model.all_tasks
        tasks_by_status: dict[int, list[Task]] = {}
        for task in all_tasks:
            tasks_by_status.setdefault(task.status_id, []).append(task)
        for status in model.statuses:
            bucket = tasks_by_status.get(status.id, [])
            title = f"({len(bucket)}) {escape_markup(status.name)}"
            cards = [TaskCard(t, classes="task-card") for t in bucket]
            col = Vertical(
                Label(title, classes="status-col-title"),
                _KanbanScrollable(*cards),
                id=f"status-col-{status.id}",
                classes="status-col",
            )
            self.mount(col)

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

