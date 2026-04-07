from __future__ import annotations

from textual.widgets import Tree
from textual.widgets._tree import TreeNode

from sticky_notes.formatting import format_task_num
from sticky_notes.models import Group, Project, Task
from sticky_notes.tui.markup import escape_markup
from sticky_notes.tui.model import GroupNode, WorkspaceModel


class WorkspaceTree(Tree[Project | Group | Task]):
    ICON_WORKSPACE = "\U0001f4e6"
    ICON_PROJECT = "\U0001f5c2\ufe0f"
    ICON_GROUP = "\U0001f4c1"
    ICON_TASK = "\U0001f4dd"

    def load(self, model: WorkspaceModel) -> None:
        self.root.set_label(
            f"{self.ICON_WORKSPACE} {escape_markup(model.workspace.name)}"
        )
        for pnode in model.projects:
            proj_branch = self.root.add(
                f"{self.ICON_PROJECT} {escape_markup(pnode.project.name)}",
                data=pnode.project,
            )
            for gnode in pnode.groups:
                self._add_group_node(proj_branch, gnode)
            for task in pnode.ungrouped_tasks:
                label = f"{self.ICON_TASK} {format_task_num(task.id)}: {escape_markup(task.title)}"
                proj_branch.add_leaf(label, data=task)
            proj_branch.expand()
        for task in model.unassigned_tasks:
            label = f"{self.ICON_TASK} {format_task_num(task.id)}: {escape_markup(task.title)}"
            self.root.add_leaf(label, data=task)
        self.root.expand()

    def show_empty(self, message: str) -> None:
        self.root.set_label(message)

    def _add_group_node(self, parent: TreeNode, group_node: GroupNode) -> None:
        branch = parent.add(
            f"{self.ICON_GROUP} {escape_markup(group_node.group.title)}",
            data=group_node.group,
        )
        for child in group_node.children:
            self._add_group_node(branch, child)
        for task in group_node.tasks:
            label = f"{self.ICON_TASK} {format_task_num(task.id)}: {escape_markup(task.title)}"
            branch.add_leaf(label, data=task)
