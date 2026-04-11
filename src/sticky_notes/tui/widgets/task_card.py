from __future__ import annotations

from textual import events
from textual.message import Message
from textual.widgets import Static

from sticky_notes.models import Task
from sticky_notes.tui.markup import escape_markup


class TaskCard(Static):
    """A focusable task card for the kanban board."""

    can_focus = True

    class Activated(Message):
        """Posted when user clicks the card."""

        def __init__(self, task: Task) -> None:
            self.task = task
            super().__init__()

    def __init__(
        self,
        task: Task,
        *,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        self.task_data = task
        content = f"{task.id:d}: {escape_markup(task.title)}"
        super().__init__(content, id=id, classes=classes)

    def on_click(self, event: events.Click) -> None:
        event.stop()
        self.focus()
        self.post_message(self.Activated(self.task_data))
