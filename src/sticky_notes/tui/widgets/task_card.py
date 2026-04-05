from __future__ import annotations

from textual.binding import Binding
from textual.message import Message
from textual.widgets import Static

from sticky_notes.formatting import format_priority, format_task_num
from sticky_notes.models import Task
from sticky_notes.tui.markup import escape_markup


class TaskCard(Static):
    can_focus = True

    DEFAULT_CSS = """
    TaskCard {
        height: auto;
        padding: 0 1;
        margin: 0 0 1 0;
        border: solid $primary;
    }
    """

    BINDINGS = [
        Binding("up", "nav('up')", show=False),
        Binding("down", "nav('down')", show=False),
        Binding("left", "nav('left')", show=False),
        Binding("right", "nav('right')", show=False),
        Binding("shift+left", "move('left')", show=False),
        Binding("shift+right", "move('right')", show=False),
        Binding("enter", "show_detail", "Detail"),
        Binding("e", "edit", "Edit"),
        Binding("m", "move_board", "Move"),
        Binding("d", "archive", "Archive"),
        Binding("delete", "archive", "Archive", show=False),
    ]

    class Navigate(Message):
        """Request directional navigation from the parent BoardView."""

        def __init__(self, direction: str) -> None:
            self.direction = direction
            super().__init__()

    class MoveRequest(Message):
        """Request to move a task to an adjacent column."""

        def __init__(self, direction: str) -> None:
            self.direction = direction
            super().__init__()

    class ShowRequest(Message):
        """Request to show task detail."""

        def __init__(self, task_id: int) -> None:
            self.task_id = task_id
            super().__init__()

    class EditRequest(Message):
        """Request to edit a task."""

        def __init__(self, task_id: int) -> None:
            self.task_id = task_id
            super().__init__()

    class ArchiveRequest(Message):
        """Request to archive a task."""

        def __init__(self, task_id: int) -> None:
            self.task_id = task_id
            super().__init__()

    class MoveBoardRequest(Message):
        """Request to move a task to a different board."""

        def __init__(self, task_id: int) -> None:
            self.task_id = task_id
            super().__init__()

    class FocusChanged(Message):
        """Notify parent that this card received focus (click or keyboard)."""

        def __init__(self, task_id: int) -> None:
            self.task_id = task_id
            super().__init__()

    def __init__(self, task_data: Task) -> None:
        self.task_data = task_data
        label = (
            f"{format_task_num(task_data.id)}  "
            f"{escape_markup(format_priority(task_data.priority))}  "
            f"{escape_markup(task_data.title)}"
        )
        super().__init__(label)

    def action_nav(self, direction: str) -> None:
        self.post_message(self.Navigate(direction))

    def action_move(self, direction: str) -> None:
        self.post_message(self.MoveRequest(direction))

    def action_show_detail(self) -> None:
        self.post_message(self.ShowRequest(self.task_data.id))

    def action_edit(self) -> None:
        self.post_message(self.EditRequest(self.task_data.id))

    def action_archive(self) -> None:
        self.post_message(self.ArchiveRequest(self.task_data.id))

    def action_move_board(self) -> None:
        self.post_message(self.MoveBoardRequest(self.task_data.id))

    def on_focus(self) -> None:
        self.post_message(self.FocusChanged(self.task_data.id))
