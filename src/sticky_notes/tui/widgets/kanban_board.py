from __future__ import annotations

from textual import events
from textual.containers import Horizontal, Vertical, ScrollableContainer
from textual.message import Message
from textual.widgets import Label

from sticky_notes.models import Task
from sticky_notes.tui.markup import escape_markup
from sticky_notes.tui.model import GroupNode, WorkspaceModel
from sticky_notes.tui.widgets.task_card import TaskCard


class _KanbanScrollable(ScrollableContainer):
    can_focus = False


class KanbanBoard(Horizontal):
    class TaskActivated(Message):
        """A task card was activated on the kanban board."""

        def __init__(self, task: Task) -> None:
            self.task = task
            super().__init__()

    def load(self, model: WorkspaceModel) -> None:
        self.remove_children()
        all_tasks = self._collect_all_tasks(model)
        tasks_by_status: dict[int, list[Task]] = {}
        for task in all_tasks:
            tasks_by_status.setdefault(task.status_id, []).append(task)
        for status in model.statuses:
            bucket = tasks_by_status.get(status.id, [])
            title = f"{escape_markup(status.name)} ({len(bucket)})"
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
        grid: list[list[TaskCard]] = []
        for col in self.query(".status-col"):
            cards = list(col.query(TaskCard))
            grid.append(cards)
        return grid

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
        pos = self._find_card_position(focused, grid)
        if pos is None:
            return False
        ci, ri = pos
        new_ci = ci + col_delta
        new_ri = ri + row_delta
        # Column movement: skip empty columns
        if col_delta != 0:
            while 0 <= new_ci < len(grid) and not grid[new_ci]:
                new_ci += col_delta
            if not (0 <= new_ci < len(grid)):
                return False
            new_ri = min(ri, len(grid[new_ci]) - 1)
        # Row movement: bounds check
        if row_delta != 0:
            if not (0 <= new_ri < len(grid[ci])):
                return False
            new_ci = ci
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

    # -- Model helpers --

    def _collect_all_tasks(self, model: WorkspaceModel) -> list[Task]:
        tasks: list[Task] = []
        for pnode in model.projects:
            for gnode in pnode.groups:
                self._collect_group_tasks(gnode, tasks)
            tasks.extend(pnode.ungrouped_tasks)
        tasks.extend(model.unassigned_tasks)
        return tasks

    def _collect_group_tasks(self, gnode: GroupNode, tasks: list[Task]) -> None:
        tasks.extend(gnode.tasks)
        for child in gnode.children:
            self._collect_group_tasks(child, tasks)
