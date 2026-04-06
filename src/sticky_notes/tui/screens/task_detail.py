from __future__ import annotations

from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Markdown, Static

from sticky_notes import service
from sticky_notes.formatting import format_priority, format_task_num, format_timestamp
from sticky_notes.tui.markup import escape_markup

if TYPE_CHECKING:
    from sticky_notes.tui.app import StickyNotesApp


class TaskDetailModal(ModalScreen[int | None]):
    DEFAULT_CSS = """
    TaskDetailModal {
        align: center middle;
    }

    TaskDetailModal #detail-container {
        width: 90%;
        max-height: 80%;
        padding: 1 2;
        border: thick $primary;
        background: $surface;
    }

    TaskDetailModal #detail-title {
        text-style: bold;
        margin-bottom: 1;
    }

    TaskDetailModal .detail-section {
        margin-bottom: 1;
    }

    TaskDetailModal .detail-label {
        text-style: bold;
        color: $accent;
    }

    TaskDetailModal .detail-history-entry {
        color: $text-muted;
    }
    """

    BINDINGS = [
        Binding("escape", "close", "Close", show=False),
        Binding("e", "edit", "Edit"),
    ]

    def __init__(self, task_id: int) -> None:
        super().__init__()
        self._task_id = task_id

    @property
    def typed_app(self) -> StickyNotesApp:
        return self.app  # type: ignore[return-value]

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="detail-container"):
            yield Static(id="detail-title")
            yield Static(id="detail-meta", classes="detail-section")
            yield Static(id="detail-deps", classes="detail-section")
            yield Static("Description", id="detail-desc-label", classes="detail-label")
            yield Markdown(id="detail-desc", classes="detail-section")
            yield Static("History", id="detail-history-label", classes="detail-label")
            yield Static(id="detail-history", classes="detail-history-entry")

    def on_mount(self) -> None:
        detail = service.get_task_detail(self.typed_app.conn, self._task_id)

        self.query_one("#detail-title", Static).update(
            f"{format_task_num(detail.id)}  {escape_markup(detail.title)}"
        )

        meta_lines = [
            f"  Status:      {escape_markup(detail.status.name)}",
        ]
        if detail.project:
            meta_lines.append(f"  Project:     {escape_markup(detail.project.name)}")
        meta_lines.append(f"  Priority:    {escape_markup(format_priority(detail.priority))}")
        if detail.due_date:
            meta_lines.append(f"  Due:         {format_timestamp(detail.due_date)}")
        meta_lines.append(f"  Created:     {format_timestamp(detail.created_at)}")
        if detail.archived:
            meta_lines.append("  Archived:    Yes")
        self.query_one("#detail-meta", Static).update("\n".join(meta_lines))

        if detail.blocked_by or detail.blocks:
            dep_lines = []
            if detail.blocked_by:
                nums = ", ".join(format_task_num(t.id) for t in detail.blocked_by)
                dep_lines.append(f"  Blocked by:  {nums}")
            if detail.blocks:
                nums = ", ".join(format_task_num(t.id) for t in detail.blocks)
                dep_lines.append(f"  Blocks:      {nums}")
            self.query_one("#detail-deps", Static).update("\n".join(dep_lines))
        else:
            self.query_one("#detail-deps", Static).display = False

        if detail.description:
            self.query_one("#detail-desc", Markdown).update(detail.description)
        else:
            self.query_one("#detail-desc-label", Static).display = False
            self.query_one("#detail-desc", Markdown).display = False

        if detail.history:
            history_lines = []
            for h in detail.history:
                old_str = h.old_value if h.old_value is not None else "(none)"
                new_str = h.new_value if h.new_value is not None else "(none)"
                history_lines.append(
                    f"  {format_timestamp(h.changed_at)}  "
                    f"{h.field}: {escape_markup(old_str)} -> "
                    f"{escape_markup(new_str)}  ({escape_markup(h.source)})"
                )
            self.query_one("#detail-history", Static).update("\n".join(history_lines))
        else:
            self.query_one("#detail-history-label", Static).display = False
            self.query_one("#detail-history", Static).display = False

    def action_close(self) -> None:
        self.dismiss(None)

    def action_edit(self) -> None:
        self.dismiss(self._task_id)
