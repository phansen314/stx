"""Kanban board — ported from the old TUI (~/code/stx). Columns are the workspace's statuses
(ordered by kanban_order); cards are the active track's tasks grouped by status_id. Grid + ijkl
navigation and the status-move message are carried over; the data source is now plain lists."""
from __future__ import annotations

from textual import events
from textual.containers import Horizontal, ScrollableContainer, Vertical
from textual.message import Message
from textual.widgets import Label

from ..markup import escape_markup
from stxc.models import Status, Task
from .task_card import TaskCard


class _KanbanScrollable(ScrollableContainer):
    can_focus = False


class KanbanColumn(Vertical):
    can_focus = True

    def __init__(self, status_id: int, *children, **kwargs) -> None:
        self.status_id = status_id
        super().__init__(*children, **kwargs)

    def on_click(self) -> None:
        self.focus()

    def key_left(self, event: events.Key) -> None:
        if self.has_focus and self.parent._focus_neighbor_column(self, -1):  # type: ignore[union-attr]
            event.stop()

    def key_right(self, event: events.Key) -> None:
        if self.has_focus and self.parent._focus_neighbor_column(self, 1):  # type: ignore[union-attr]
            event.stop()

    def key_down(self, event: events.Key) -> None:
        if not self.has_focus:
            return
        cards = list(self.query(TaskCard))
        if cards:
            self.screen.set_focus(cards[0])
            event.stop()

    # ijkl home-row aliases (parity with the old TUI): j/l = prev/next column, k = into cards.
    def key_j(self, event: events.Key) -> None:
        self.key_left(event)

    def key_l(self, event: events.Key) -> None:
        self.key_right(event)

    def key_k(self, event: events.Key) -> None:
        self.key_down(event)


class KanbanBoard(Horizontal):
    _grid: list[list[TaskCard]] | None = None
    _status_names: dict[int, str] = {}

    class TaskActivated(Message):
        def __init__(self, task: Task) -> None:
            self.task = task
            super().__init__()

    class TaskStatusMove(Message):
        def __init__(self, task: Task, new_status_id: int) -> None:
            self.task = task
            self.new_status_id = new_status_id
            super().__init__()

    @staticmethod
    def _by_status(tasks: list[Task]) -> dict[int, list[Task]]:
        out: dict[int, list[Task]] = {}
        for t in tasks:
            out.setdefault(t.status_id, []).append(t)
        return out

    def _build_column(self, status: Status, tasks: list[Task]) -> KanbanColumn:
        title = f"({len(tasks)}) {escape_markup(status.name)}"
        cards = [TaskCard(t, classes="task-card") for t in tasks]
        return KanbanColumn(
            status.id,
            Label(title, classes="status-col-title"),
            _KanbanScrollable(*cards),
            id=f"status-col-{status.id}",
            classes="status-col",
        )

    async def load(self, statuses: list[Status], tasks: list[Task]) -> None:
        self._grid = None
        self._status_names = {s.id: s.name for s in statuses}
        # Drop focus before tearing the board down — otherwise removing the focused card makes
        # Textual blip focus to the parent (the tree), which the app would record as a panel
        # switch. The app restores board focus right after this returns. (Mirrors old stx.)
        if self.screen is not None and isinstance(self.screen.focused, (TaskCard, KanbanColumn)):
            self.screen.set_focus(None)
        await self.remove_children()
        by_status = self._by_status(tasks)
        for status in statuses:
            await self.mount(self._build_column(status, by_status.get(status.id, [])))

    def on_task_card_activated(self, event: TaskCard.Activated) -> None:
        event.stop()
        self.post_message(self.TaskActivated(event.task))

    # ── grid navigation ──
    def _build_grid(self) -> list[list[TaskCard]]:
        if self._grid is None:
            self._grid = [list(col.query(TaskCard)) for col in self.query(".status-col")]
        return self._grid

    def _find(self, card: TaskCard, grid: list[list[TaskCard]]) -> tuple[int, int] | None:
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
        pos = self._find(focused, grid)
        if pos is None:
            return False
        ci, ri = pos
        if col_delta != 0:
            idx = (non_empty.index(ci) + col_delta) % len(non_empty)
            new_ci = non_empty[idx]
            new_ri = min(ri, len(grid[new_ci]) - 1)
        else:
            new_ci = ci
            if row_delta == -1 and ri == 0:
                self.screen.set_focus(self.query_one(f"#status-col-{focused.task_data.status_id}", KanbanColumn))
                return True
            new_ri = max(0, min(ri + row_delta, len(grid[ci]) - 1))
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

    # ijkl home-row aliases for card grid navigation (parity with the old TUI): i/k = up/down,
    # j/l = left/right.
    def key_i(self, event: events.Key) -> None:
        self.key_up(event)

    def key_k(self, event: events.Key) -> None:
        self.key_down(event)

    def key_j(self, event: events.Key) -> None:
        self.key_left(event)

    def key_l(self, event: events.Key) -> None:
        self.key_right(event)

    def _move_status(self, delta: int) -> bool:
        """Post a TaskStatusMove for the focused card toward the neighbour column (app validates legality)."""
        focused = self.screen.focused
        if not isinstance(focused, TaskCard):
            return False
        cols = list(self.query(".status-col"))
        current = f"status-col-{focused.task_data.status_id}"
        ci = next((i for i, c in enumerate(cols) if c.id == current), None)
        if ci is None:
            return False
        new_ci = ci + delta
        if new_ci < 0 or new_ci >= len(cols):
            return False
        status_id = int(cols[new_ci].id.removeprefix("status-col-"))  # type: ignore[union-attr]
        self.post_message(self.TaskStatusMove(focused.task_data, status_id))
        return True

    def _focus_neighbor_column(self, col: KanbanColumn, delta: int) -> bool:
        cols = list(self.query(".status-col"))
        ci = next((i for i, c in enumerate(cols) if c is col), None)
        if ci is None:
            return False
        self.screen.set_focus(cols[(ci + delta) % len(cols)])
        return True
