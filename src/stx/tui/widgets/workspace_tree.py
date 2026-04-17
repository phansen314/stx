from __future__ import annotations

from textual import events
from textual.message import Message
from textual.widgets import Tree
from textual.widgets._tree import TreeNode

from stx.models import Group, Task, Workspace
from stx.tui.markup import escape_markup
from stx.tui.model import GroupNode, WorkspaceModel


class WorkspaceTree(Tree[Workspace | Group | Task]):
    ICON_WORKSPACE = "\U0001f4e6"
    ICON_GROUP = "\U0001f4c1"
    ICON_TASK = "\U0001f4dd"

    _last_workspace_id: int | None = None

    class TaskSelected(Message):
        """A task node was selected in the tree."""

        def __init__(self, task: Task) -> None:
            self.task = task
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

    class TreeFilterChanged(Message):
        """The tree cursor moved to a node that changes the kanban filter scope."""

        def __init__(self, group_id: int | None) -> None:
            self.group_id = group_id
            super().__init__()

    @staticmethod
    def _count_group_tasks(gnode: GroupNode) -> int:
        count = len(gnode.tasks)
        for child in gnode.children:
            count += WorkspaceTree._count_group_tasks(child)
        return count

    @staticmethod
    def _workspace_id_from_data(data: Workspace | Group | Task | None) -> int | None:
        if isinstance(data, Workspace):
            return data.id
        if isinstance(data, (Group, Task)):
            return data.workspace_id
        return None

    @staticmethod
    def _node_key(data: Workspace | Group | Task | None) -> tuple[str, int] | None:
        if isinstance(data, Workspace):
            return ("workspace", data.id)
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

    def load(
        self, models: dict[int, WorkspaceModel], expand_workspace_id: int | None = None
    ) -> None:
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
                    break

    def _populate_workspace_node(self, ws_node: TreeNode, model: WorkspaceModel) -> None:
        for gnode in model.root_groups:
            self._add_group_node(ws_node, gnode)
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
        data = event.node.data
        ws_id = self._workspace_id_from_data(data)
        if ws_id is not None and ws_id != self._last_workspace_id:
            self._last_workspace_id = ws_id
            self.post_message(self.WorkspaceChanged(ws_id))
        if isinstance(data, Workspace):
            self.post_message(self.TreeFilterChanged(group_id=None))
        elif isinstance(data, Group):
            self.post_message(self.TreeFilterChanged(group_id=data.id))
        elif isinstance(data, Task):
            self.post_message(self.TreeFilterChanged(group_id=data.group_id))

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        event.stop()
        node_data = event.node.data
        if isinstance(node_data, Task):
            self.post_message(self.TaskSelected(node_data))
        elif isinstance(node_data, Group):
            self.post_message(self.GroupSelected(node_data))
