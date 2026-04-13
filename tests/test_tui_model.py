from __future__ import annotations

import pytest

from stx.models import Group
from stx.tui.model import (
    GroupNode,
    flatten_group_tree,
    load_workspace_model,
)
from tests.helpers import (
    insert_group,
    insert_status,
    insert_task,
    insert_workspace,
)


class TestLoadWorkspaceModelNotFound:
    def test_raises_lookup_error(self, conn):
        with pytest.raises(LookupError):
            load_workspace_model(conn, 999)


class TestLoadWorkspaceModelBasic:
    def test_loads_workspace(self, conn):
        ws_id = insert_workspace(conn)
        insert_status(conn, ws_id)
        model = load_workspace_model(conn, ws_id)
        assert model.workspace.id == ws_id

    def test_loads_statuses(self, conn):
        ws_id = insert_workspace(conn)
        insert_status(conn, ws_id, "todo")
        insert_status(conn, ws_id, "done")
        model = load_workspace_model(conn, ws_id)
        assert len(model.statuses) == 2
        assert {s.name for s in model.statuses} == {"todo", "done"}

    def test_loads_root_groups(self, conn):
        ws_id = insert_workspace(conn)
        insert_status(conn, ws_id)
        g_id = insert_group(conn, ws_id, "root-group")
        model = load_workspace_model(conn, ws_id)
        assert len(model.root_groups) == 1
        assert model.root_groups[0].group.id == g_id

    def test_unassigned_tasks(self, conn):
        ws_id = insert_workspace(conn)
        s_id = insert_status(conn, ws_id)
        t_id = insert_task(conn, ws_id, "loose task", s_id)
        model = load_workspace_model(conn, ws_id)
        assert len(model.unassigned_tasks) == 1
        assert model.unassigned_tasks[0].id == t_id

    def test_excludes_archived_tasks(self, conn):
        ws_id = insert_workspace(conn)
        s_id = insert_status(conn, ws_id)
        active = insert_task(conn, ws_id, "active", s_id)
        archived = insert_task(conn, ws_id, "archived", s_id)
        conn.execute("UPDATE tasks SET archived = 1 WHERE id = ?", (archived,))
        model = load_workspace_model(conn, ws_id)
        assert len(model.unassigned_tasks) == 1
        assert model.unassigned_tasks[0].id == active

    def test_excludes_archived_groups(self, conn):
        ws_id = insert_workspace(conn)
        insert_status(conn, ws_id)
        insert_group(conn, ws_id, "active-group")
        arch_g = insert_group(conn, ws_id, "archived-group")
        conn.execute("UPDATE groups SET archived = 1 WHERE id = ?", (arch_g,))
        model = load_workspace_model(conn, ws_id)
        assert len(model.root_groups) == 1
        assert model.root_groups[0].group.title == "active-group"

    def test_empty_workspace(self, conn):
        ws_id = insert_workspace(conn)
        insert_status(conn, ws_id)
        model = load_workspace_model(conn, ws_id)
        assert len(model.root_groups) == 0
        assert len(model.unassigned_tasks) == 0


class TestTreeStructure:
    def test_task_in_group(self, conn):
        ws_id = insert_workspace(conn)
        s_id = insert_status(conn, ws_id)
        g_id = insert_group(conn, ws_id, "group1")
        t_id = insert_task(conn, ws_id, "grouped", s_id)
        conn.execute("UPDATE tasks SET group_id = ? WHERE id = ?", (g_id, t_id))

        model = load_workspace_model(conn, ws_id)
        assert len(model.root_groups) == 1
        gnode = model.root_groups[0]
        assert gnode.group.id == g_id
        assert len(gnode.tasks) == 1
        assert gnode.tasks[0].id == t_id
        assert len(model.unassigned_tasks) == 0

    def test_unassigned_task_in_workspace(self, conn):
        ws_id = insert_workspace(conn)
        s_id = insert_status(conn, ws_id)
        insert_group(conn, ws_id, "group1")
        t_id = insert_task(conn, ws_id, "unassigned", s_id)

        model = load_workspace_model(conn, ws_id)
        assert len(model.unassigned_tasks) == 1
        assert model.unassigned_tasks[0].id == t_id
        assert len(model.root_groups[0].tasks) == 0

    def test_nested_groups(self, conn):
        ws_id = insert_workspace(conn)
        s_id = insert_status(conn, ws_id)
        parent_g = insert_group(conn, ws_id, "parent")
        child_g = insert_group(conn, ws_id, "child", parent_id=parent_g)
        t_id = insert_task(conn, ws_id, "child task", s_id)
        conn.execute("UPDATE tasks SET group_id = ? WHERE id = ?", (child_g, t_id))

        model = load_workspace_model(conn, ws_id)
        assert len(model.root_groups) == 1
        root = model.root_groups[0]
        assert root.group.id == parent_g
        assert len(root.tasks) == 0
        assert len(root.children) == 1
        assert root.children[0].group.id == child_g
        assert len(root.children[0].tasks) == 1
        assert root.children[0].tasks[0].id == t_id

    def test_mixed_assignment(self, conn):
        """Tasks split across grouped and unassigned."""
        ws_id = insert_workspace(conn)
        s_id = insert_status(conn, ws_id)
        g_id = insert_group(conn, ws_id, "group1")

        grouped = insert_task(conn, ws_id, "grouped", s_id)
        conn.execute("UPDATE tasks SET group_id = ? WHERE id = ?", (g_id, grouped))
        unassigned = insert_task(conn, ws_id, "unassigned", s_id)

        model = load_workspace_model(conn, ws_id)
        assert len(model.root_groups[0].tasks) == 1
        assert model.root_groups[0].tasks[0].id == grouped
        assert len(model.unassigned_tasks) == 1
        assert model.unassigned_tasks[0].id == unassigned


class TestFlattenGroupTree:
    def _group(self, id: int, title: str) -> Group:
        return Group(
            id=id,
            workspace_id=1,
            title=title,
            description=None,
            parent_id=None,
            archived=False,
            created_at=0,
            metadata={},
        )

    def _node(self, id: int, title: str, children: tuple[GroupNode, ...] = ()) -> GroupNode:
        return GroupNode(group=self._group(id, title), tasks=(), children=children)

    def test_empty(self):
        assert flatten_group_tree(()) == []

    def test_single_root(self):
        tree = (self._node(1, "Frontend"),)
        assert flatten_group_tree(tree) == [("Frontend", 1)]

    def test_multiple_roots_preserve_order(self):
        tree = (self._node(1, "Frontend"), self._node(2, "Backend"))
        assert flatten_group_tree(tree) == [("Frontend", 1), ("Backend", 2)]

    def test_nested_children(self):
        login = self._node(2, "Login")
        frontend = self._node(1, "Frontend", children=(login,))
        assert flatten_group_tree((frontend,)) == [
            ("Frontend", 1),
            ("Frontend > Login", 2),
        ]

    def test_deep_nesting(self):
        oauth = self._node(3, "OAuth")
        login = self._node(2, "Login", children=(oauth,))
        frontend = self._node(1, "Frontend", children=(login,))
        assert flatten_group_tree((frontend,)) == [
            ("Frontend", 1),
            ("Frontend > Login", 2),
            ("Frontend > Login > OAuth", 3),
        ]

    def test_parent_emitted_before_children(self):
        """Depth-first pre-order: parents come before any descendants."""
        a1 = self._node(3, "A1")
        a2 = self._node(4, "A2")
        a = self._node(1, "A", children=(a1, a2))
        b = self._node(2, "B")
        result = flatten_group_tree((a, b))
        labels = [label for label, _ in result]
        assert labels == ["A", "A > A1", "A > A2", "B"]
