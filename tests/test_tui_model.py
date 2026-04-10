from __future__ import annotations

import pytest

from sticky_notes.models import Group
from sticky_notes.tui.model import (
    GroupNode,
    ProjectNode,
    WorkspaceModel,
    flatten_group_tree,
    load_workspace_model,
)
from tests.helpers import (
    insert_group,
    insert_group_dependency,
    insert_project,
    insert_status,
    insert_task,
    insert_task_dependency,
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

    def test_loads_projects(self, conn):
        ws_id = insert_workspace(conn)
        insert_status(conn, ws_id)
        p_id = insert_project(conn, ws_id, "proj1")
        model = load_workspace_model(conn, ws_id)
        assert len(model.projects) == 1
        assert model.projects[0].project.id == p_id

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

    def test_excludes_archived_projects(self, conn):
        ws_id = insert_workspace(conn)
        insert_status(conn, ws_id)
        insert_project(conn, ws_id, "active-proj")
        arch_p = insert_project(conn, ws_id, "archived-proj")
        conn.execute("UPDATE projects SET archived = 1 WHERE id = ?", (arch_p,))
        model = load_workspace_model(conn, ws_id)
        assert len(model.projects) == 1
        assert model.projects[0].project.name == "active-proj"

    def test_excludes_archived_groups(self, conn):
        ws_id = insert_workspace(conn)
        insert_status(conn, ws_id)
        p_id = insert_project(conn, ws_id)
        insert_group(conn, p_id, "active-group")
        arch_g = insert_group(conn, p_id, "archived-group")
        conn.execute("UPDATE groups SET archived = 1 WHERE id = ?", (arch_g,))
        model = load_workspace_model(conn, ws_id)
        assert len(model.projects[0].groups) == 1
        assert model.projects[0].groups[0].group.title == "active-group"

    def test_empty_workspace(self, conn):
        ws_id = insert_workspace(conn)
        insert_status(conn, ws_id)
        model = load_workspace_model(conn, ws_id)
        assert len(model.projects) == 0
        assert len(model.unassigned_tasks) == 0


class TestTreeStructure:
    def test_task_in_group(self, conn):
        ws_id = insert_workspace(conn)
        s_id = insert_status(conn, ws_id)
        p_id = insert_project(conn, ws_id)
        g_id = insert_group(conn, p_id, "group1")
        t_id = insert_task(conn, ws_id, "grouped", s_id, project_id=p_id)
        conn.execute("UPDATE tasks SET group_id = ? WHERE id = ?", (g_id, t_id))

        model = load_workspace_model(conn, ws_id)
        pnode = model.projects[0]
        assert len(pnode.groups) == 1
        assert pnode.groups[0].group.id == g_id
        assert len(pnode.groups[0].tasks) == 1
        assert pnode.groups[0].tasks[0].id == t_id
        assert len(pnode.ungrouped_tasks) == 0

    def test_ungrouped_task_in_project(self, conn):
        ws_id = insert_workspace(conn)
        s_id = insert_status(conn, ws_id)
        p_id = insert_project(conn, ws_id)
        t_id = insert_task(conn, ws_id, "ungrouped", s_id, project_id=p_id)

        model = load_workspace_model(conn, ws_id)
        pnode = model.projects[0]
        assert len(pnode.ungrouped_tasks) == 1
        assert pnode.ungrouped_tasks[0].id == t_id
        assert len(pnode.groups) == 0

    def test_nested_groups(self, conn):
        ws_id = insert_workspace(conn)
        s_id = insert_status(conn, ws_id)
        p_id = insert_project(conn, ws_id)
        parent_g = insert_group(conn, p_id, "parent")
        child_g = insert_group(conn, p_id, "child", parent_id=parent_g)
        t_id = insert_task(conn, ws_id, "child task", s_id, project_id=p_id)
        conn.execute("UPDATE tasks SET group_id = ? WHERE id = ?", (child_g, t_id))

        model = load_workspace_model(conn, ws_id)
        pnode = model.projects[0]
        assert len(pnode.groups) == 1
        root = pnode.groups[0]
        assert root.group.id == parent_g
        assert len(root.tasks) == 0
        assert len(root.children) == 1
        assert root.children[0].group.id == child_g
        assert len(root.children[0].tasks) == 1
        assert root.children[0].tasks[0].id == t_id

    def test_mixed_assignment(self, conn):
        """Tasks split across grouped, ungrouped-in-project, and unassigned."""
        ws_id = insert_workspace(conn)
        s_id = insert_status(conn, ws_id)
        p_id = insert_project(conn, ws_id)
        g_id = insert_group(conn, p_id, "group1")

        grouped = insert_task(conn, ws_id, "grouped", s_id, project_id=p_id)
        conn.execute("UPDATE tasks SET group_id = ? WHERE id = ?", (g_id, grouped))
        ungrouped = insert_task(conn, ws_id, "ungrouped", s_id, project_id=p_id)
        unassigned = insert_task(conn, ws_id, "unassigned", s_id)

        model = load_workspace_model(conn, ws_id)
        pnode = model.projects[0]
        assert len(pnode.groups[0].tasks) == 1
        assert pnode.groups[0].tasks[0].id == grouped
        assert len(pnode.ungrouped_tasks) == 1
        assert pnode.ungrouped_tasks[0].id == ungrouped
        assert len(model.unassigned_tasks) == 1
        assert model.unassigned_tasks[0].id == unassigned


class TestDependencyOrdering:
    def test_blocked_by_map_loaded(self, conn):
        ws_id = insert_workspace(conn)
        s_id = insert_status(conn, ws_id)
        t1 = insert_task(conn, ws_id, "first", s_id)
        t2 = insert_task(conn, ws_id, "second", s_id)
        insert_task_dependency(conn, t2, t1)  # t2 depends on t1

        model = load_workspace_model(conn, ws_id)
        assert t1 in model.blocked_by_map.get(t2, ())
        assert t2 not in model.blocked_by_map.get(t1, ())

    def test_all_tasks_sorted_by_dependency(self, conn):
        ws_id = insert_workspace(conn)
        s_id = insert_status(conn, ws_id)
        # Insert in reverse dependency order
        t3 = insert_task(conn, ws_id, "third", s_id)
        t2 = insert_task(conn, ws_id, "second", s_id)
        t1 = insert_task(conn, ws_id, "first", s_id)
        insert_task_dependency(conn, t2, t1)  # t2 depends on t1
        insert_task_dependency(conn, t3, t2)  # t3 depends on t2

        model = load_workspace_model(conn, ws_id)
        ids = [t.id for t in model.all_tasks]
        assert ids.index(t1) < ids.index(t2) < ids.index(t3)

    def test_unrelated_tasks_keep_original_order(self, conn):
        ws_id = insert_workspace(conn)
        s_id = insert_status(conn, ws_id)
        t1 = insert_task(conn, ws_id, "A", s_id)
        t2 = insert_task(conn, ws_id, "B", s_id)
        t3 = insert_task(conn, ws_id, "C", s_id)

        model = load_workspace_model(conn, ws_id)
        ids = [t.id for t in model.all_tasks]
        assert ids == [t1, t2, t3]

    def test_ungrouped_project_tasks_sorted(self, conn):
        ws_id = insert_workspace(conn)
        s_id = insert_status(conn, ws_id)
        p_id = insert_project(conn, ws_id)
        t2 = insert_task(conn, ws_id, "dependent", s_id, project_id=p_id)
        t1 = insert_task(conn, ws_id, "prerequisite", s_id, project_id=p_id)
        insert_task_dependency(conn, t2, t1)

        model = load_workspace_model(conn, ws_id)
        ungrouped_ids = [t.id for t in model.projects[0].ungrouped_tasks]
        assert ungrouped_ids.index(t1) < ungrouped_ids.index(t2)

    def test_group_tasks_sorted(self, conn):
        ws_id = insert_workspace(conn)
        s_id = insert_status(conn, ws_id)
        p_id = insert_project(conn, ws_id)
        g_id = insert_group(conn, p_id)
        t2 = insert_task(conn, ws_id, "dependent", s_id, project_id=p_id)
        t1 = insert_task(conn, ws_id, "prerequisite", s_id, project_id=p_id)
        conn.execute("UPDATE tasks SET group_id = ? WHERE id IN (?, ?)", (g_id, t1, t2))
        insert_task_dependency(conn, t2, t1)

        model = load_workspace_model(conn, ws_id)
        group_ids = [t.id for t in model.projects[0].groups[0].tasks]
        assert group_ids.index(t1) < group_ids.index(t2)

    def test_cross_column_deps_dont_affect_within_column_order(self, conn):
        """If A (todo) depends on B (done), A's position in todo is unaffected."""
        ws_id = insert_workspace(conn)
        todo = insert_status(conn, ws_id, "todo")
        done = insert_status(conn, ws_id, "done")
        t_done = insert_task(conn, ws_id, "done task", done)
        t_todo1 = insert_task(conn, ws_id, "first todo", todo)
        t_todo2 = insert_task(conn, ws_id, "second todo", todo)
        insert_task_dependency(conn, t_todo2, t_done)  # cross-column dep

        model = load_workspace_model(conn, ws_id)
        # Within the todo column subset, t_todo1 and t_todo2 have no
        # within-column dependency, so original order preserved
        todo_tasks = [t for t in model.all_tasks if t.status_id == todo]
        ids = [t.id for t in todo_tasks]
        assert ids == [t_todo1, t_todo2]

    def test_groups_sorted_by_dependency(self, conn):
        ws_id = insert_workspace(conn)
        s_id = insert_status(conn, ws_id)
        p_id = insert_project(conn, ws_id)
        # Insert in reverse dependency order
        g2 = insert_group(conn, p_id, "dependent-group")
        g1 = insert_group(conn, p_id, "prerequisite-group")
        insert_group_dependency(conn, g2, g1)

        model = load_workspace_model(conn, ws_id)
        group_ids = [g.group.id for g in model.projects[0].groups]
        assert group_ids.index(g1) < group_ids.index(g2)

    def test_nested_groups_sorted_by_dependency(self, conn):
        ws_id = insert_workspace(conn)
        s_id = insert_status(conn, ws_id)
        p_id = insert_project(conn, ws_id)
        parent = insert_group(conn, p_id, "parent")
        c2 = insert_group(conn, p_id, "child-dependent", parent_id=parent)
        c1 = insert_group(conn, p_id, "child-prereq", parent_id=parent)
        insert_group_dependency(conn, c2, c1)

        model = load_workspace_model(conn, ws_id)
        children = model.projects[0].groups[0].children
        child_ids = [c.group.id for c in children]
        assert child_ids.index(c1) < child_ids.index(c2)


class TestFlattenGroupTree:
    def _group(self, id: int, title: str) -> Group:
        return Group(
            id=id, workspace_id=1, project_id=1, title=title, description=None,
            parent_id=None, position=0, archived=False, created_at=0, metadata={},
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
