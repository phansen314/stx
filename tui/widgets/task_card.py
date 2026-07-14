from __future__ import annotations

from textual import events
from textual.message import Message
from textual.widgets import Static

from ..markup import escape_markup
from stxc.models import Task


class TaskCard(Static):
    """A focusable task card for the kanban board."""

    can_focus = True

    class Activated(Message):
        def __init__(self, task: Task) -> None:
            self.task = task
            super().__init__()

    def __init__(self, task: Task, *, id: str | None = None, classes: str | None = None) -> None:
        self.task_data = task
        super().__init__(self._format(task), id=id, classes=classes)

    @staticmethod
    def _format(task: Task) -> str:
        prio = f" [dim](P{task.priority})[/dim]" if task.priority else ""
        return f"{task.id:d}: {escape_markup(task.title)}{prio}"

    def refresh_from(self, task: Task) -> None:
        self.task_data = task
        self.update(self._format(task))

    def on_click(self, event: events.Click) -> None:
        event.stop()
        self.focus()
        self.post_message(self.Activated(self.task_data))
