from __future__ import annotations

from textual import events
from textual.message import Message
from textual.widgets import Tree
from textual.widgets._tree import TreeNode

from sticky_notes.models import Group, Project, Task, Workspace
from sticky_notes.tui.markup import escape_markup
from sticky_notes.tui.model import GroupNode, ProjectNode, WorkspaceModel


class WorkspaceTree(Tree[Workspace | Project | Group | Task]):
    ICON_WORKSPACE = "\U0001f4e6"
    ICON_PROJECT = "\U0001f5c2\ufe0f"
    ICON_GROUP = "\U0001f4c1"
    ICON_TASK = "\U0001f4dd"

    _last_workspace_id: int | None = None

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

    class WorkspaceChanged(Message):
        """The cursor moved to a node in a different workspace."""

        def __init__(self, workspace_id: int) -> None:
            self.workspace_id = workspace_id
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

    @staticmethod
    def _workspace_id_from_data(data: Workspace | Project | Group | Task | None) -> int | None:
        if isinstance(data, Workspace):
            return data.id
        if isinstance(data, (Project, Group, Task)):
            return data.workspace_id
        return None

    @staticmethod
    def _node_key(data: Workspace | Project | Group | Task | None) -> tuple[str, int] | None:
        if isinstance(data, Workspace):
            return ("workspace", data.id)
        if isinstance(data, Project):
            return ("project", data.id)
        if isinstance(data, Group):
            return ("group", data.id)
        return None

    def _snapshot_expanded(self) -> set[tuple[str, int]]:
        expanded: set[tuple[str, int]] = set()
        def _walk(node: TreeNode) -> None:
            key = self._node_key(node.data)
            if key is not None and node.is_expanded:
                expanded.add(key)
            for child in node.children:
                _walk(child)
        _walk(self.root)
        return expanded

    def _restore_expanded(self, snapshot: set[tuple[str, int]]) -> None:
        def _walk(node: TreeNode) -> None:
            key = self._node_key(node.data)
            if key is not None and key in snapshot:
                node.expand()
            for child in node.children:
                _walk(child)
        _walk(self.root)

    def load(self, models: dict[int, WorkspaceModel], expand_workspace_id: int | None = None) -> None:
        snapshot = self._snapshot_expanded() if self.root.children else None
        self.clear()
        self._last_workspace_id = expand_workspace_id
        self.root.set_label("Workspaces")
        self.root.data = None
        for model in models.values():
            total = len(model.all_tasks)
            ws_node = self.root.add(
                f"{self.ICON_WORKSPACE} ({total}) {escape_markup(model.workspace.name)}",
                data=model.workspace,
            )
            self._populate_workspace_node(ws_node, model)
        self.root.expand()
        if snapshot is not None:
            self._restore_expanded(snapshot)
        if expand_workspace_id is not None:
            for child in self.root.children:
                if isinstance(child.data, Workspace) and child.data.id == expand_workspace_id:
                    child.expand()
                    if snapshot is None:
                        for proj in child.children:
                            if isinstance(getattr(proj, "data", None), Project):
                                proj.expand()
                    break

    def _populate_workspace_node(self, ws_node, model: WorkspaceModel) -> None:
        for pnode in model.projects:
            pcount = self._count_project_tasks(pnode)
            proj_branch = ws_node.add(
                f"{self.ICON_PROJECT} ({pcount}) {escape_markup(pnode.project.name)}",
                data=pnode.project,
            )
            for gnode in pnode.groups:
                self._add_group_node(proj_branch, gnode)
            for task in pnode.ungrouped_tasks:
                label = f"{self.ICON_TASK} {task.id:d}: {escape_markup(task.title)}"
                proj_branch.add_leaf(label, data=task)
        for task in model.unassigned_tasks:
            label = f"{self.ICON_TASK} {task.id:d}: {escape_markup(task.title)}"
            ws_node.add_leaf(label, data=task)

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

    # ijkl aliases (home-row navigation)

    def key_i(self, event: events.Key) -> None:
        self.action_cursor_up()
        event.stop()

    def key_k(self, event: events.Key) -> None:
        self.action_cursor_down()
        event.stop()

    def key_j(self, event: events.Key) -> None:
        self.key_left(event)

    def key_l(self, event: events.Key) -> None:
        self.key_right(event)

    def on_tree_node_highlighted(self, event: Tree.NodeHighlighted) -> None:
        ws_id = self._workspace_id_from_data(event.node.data)
        if ws_id is not None and ws_id != self._last_workspace_id:
            self._last_workspace_id = ws_id
            self.post_message(self.WorkspaceChanged(ws_id))

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        event.stop()
        node_data = event.node.data
        if isinstance(node_data, Task):
            self.post_message(self.TaskSelected(node_data))
        elif isinstance(node_data, Project):
            self.post_message(self.ProjectSelected(node_data))
        elif isinstance(node_data, Group):
            self.post_message(self.GroupSelected(node_data))
