from __future__ import annotations

from textual.containers import Horizontal, Vertical, ScrollableContainer
from textual.widgets import Label

from sticky_notes.formatting import format_task_num
from sticky_notes.models import Task
from sticky_notes.tui.markup import escape_markup
from sticky_notes.tui.model import GroupNode, WorkspaceModel


class KanbanBoard(Horizontal):
    def load(self, model: WorkspaceModel) -> None:
        self.remove_children()
        all_tasks = self._collect_all_tasks(model)
        tasks_by_status: dict[int, list[Task]] = {}
        for task in all_tasks:
            tasks_by_status.setdefault(task.status_id, []).append(task)
        for status in model.statuses:
            bucket = tasks_by_status.get(status.id, [])
            title = f"{escape_markup(status.name)} ({len(bucket)})"
            card_labels = [
                Label(
                    f"{format_task_num(t.id)}: {escape_markup(t.title)}",
                    classes="task-card",
                )
                for t in bucket
            ]
            col = Vertical(
                Label(title, classes="status-col-title"),
                ScrollableContainer(*card_labels),
                id=f"status-col-{status.id}",
                classes="status-col",
            )
            self.mount(col)

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
