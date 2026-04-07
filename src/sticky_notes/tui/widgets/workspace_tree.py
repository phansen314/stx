from __future__ import annotations

from textual import events
from textual.message import Message
from textual.widgets import Tree
from textual.widgets._tree import TreeNode

from sticky_notes.models import Group, Project, Task
from sticky_notes.tui.markup import escape_markup
from sticky_notes.tui.model import GroupNode, ProjectNode, WorkspaceModel


class WorkspaceTree(Tree[Project | Group | Task]):
    ICON_WORKSPACE = "\U0001f4e6"
    ICON_PROJECT = "\U0001f5c2\ufe0f"
    ICON_GROUP = "\U0001f4c1"
    ICON_TASK = "\U0001f4dd"

    class TaskSelected(Message):
        """A task node was selected in the tree."""

        def __init__(self, task: Task) -> None:
            self.task = task
            super().__init__()

    class ProjectSelected(Message):
        """A project node was selected in the tree."""

        def __init__(self, project: Project) -> None:
            self.project = project
            super().__init__()

    class GroupSelected(Message):
        """A group node was selected in the tree."""

        def __init__(self, group: Group) -> None:
            self.group = group
            super().__init__()

    @staticmethod
    def _count_group_tasks(gnode: GroupNode) -> int:
        count = len(gnode.tasks)
        for child in gnode.children:
            count += WorkspaceTree._count_group_tasks(child)
        return count

    @staticmethod
    def _count_project_tasks(pnode: ProjectNode) -> int:
        count = len(pnode.ungrouped_tasks)
        for gnode in pnode.groups:
            count += WorkspaceTree._count_group_tasks(gnode)
        return count

    def load(self, model: WorkspaceModel) -> None:
        self.clear()
        total = len(model.all_tasks)
        self.root.set_label(
            f"{self.ICON_WORKSPACE} ({total}) {escape_markup(model.workspace.name)}"
        )
        for pnode in model.projects:
            pcount = self._count_project_tasks(pnode)
            proj_branch = self.root.add(
                f"{self.ICON_PROJECT} ({pcount}) {escape_markup(pnode.project.name)}",
                data=pnode.project,
            )
            for gnode in pnode.groups:
                self._add_group_node(proj_branch, gnode)
            for task in pnode.ungrouped_tasks:
                label = f"{self.ICON_TASK} {task.id:d}: {escape_markup(task.title)}"
                proj_branch.add_leaf(label, data=task)
            proj_branch.expand()
        for task in model.unassigned_tasks:
            label = f"{self.ICON_TASK} {task.id:d}: {escape_markup(task.title)}"
            self.root.add_leaf(label, data=task)
        self.root.expand()

    def show_empty(self, message: str) -> None:
        self.root.set_label(message)

    def _add_group_node(self, parent: TreeNode, group_node: GroupNode) -> None:
        gcount = self._count_group_tasks(group_node)
        branch = parent.add(
            f"{self.ICON_GROUP} ({gcount}) {escape_markup(group_node.group.title)}",
            data=group_node.group,
        )
        for child in group_node.children:
            self._add_group_node(branch, child)
        for task in group_node.tasks:
            label = f"{self.ICON_TASK} {task.id:d}: {escape_markup(task.title)}"
            branch.add_leaf(label, data=task)

    def key_left(self, event: events.Key) -> None:
        node = self.cursor_node
        if node is None:
            return
        if node.is_expanded:
            node.collapse()
        elif node.parent is not None:
            self.select_node(node.parent)
            self.scroll_to_node(node.parent)
        event.stop()

    def key_right(self, event: events.Key) -> None:
        node = self.cursor_node
        if node is None:
            return
        if node.allow_expand and not node.is_expanded:
            node.expand()
        elif node.is_expanded and node.children:
            self.select_node(node.children[0])
            self.scroll_to_node(node.children[0])
        event.stop()

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        event.stop()
        node_data = event.node.data
        if isinstance(node_data, Task):
            self.post_message(self.TaskSelected(node_data))
        elif isinstance(node_data, Project):
            self.post_message(self.ProjectSelected(node_data))
        elif isinstance(node_data, Group):
            self.post_message(self.GroupSelected(node_data))
