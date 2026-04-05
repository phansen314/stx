from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Static

from sticky_notes.models import Column, Task
from sticky_notes.tui.markup import escape_markup
from sticky_notes.tui.widgets.task_card import TaskCard


class ColumnWidget(Vertical):
    DEFAULT_CSS = """
    ColumnWidget {
        width: 1fr;
        border: solid $primary;
        overflow-y: auto;
        height: 100%;
        padding: 0 1;
    }
    """

    def __init__(self, column: Column, tasks: tuple[Task, ...]) -> None:
        super().__init__()
        self.column = column
        self._tasks = tasks

    def compose(self) -> ComposeResult:
        yield Static(
            f"{escape_markup(self.column.name)} ({len(self._tasks)})",
            classes="column-header",
        )
        for task in self._tasks:
            yield TaskCard(task)
