from __future__ import annotations

from pathlib import Path

import pytest

from sticky_notes import service
from sticky_notes.active_workspace import set_active_workspace_id
from sticky_notes.connection import get_connection, init_db
from sticky_notes.models import Group, Project, Task
from sticky_notes.tui.app import StickyNotesApp
from sticky_notes.tui.widgets import TaskCard


class TestTreePopulation:
    @pytest.fixture
    def app(self, seeded_tui_db):
        db_path, ids = seeded_tui_db
        return StickyNotesApp(db_path=db_path)

    async def test_root_label_is_workspace_name(self, app):
        async with app.run_test():
            tree = app.query_one("#workspaces-tree")
            assert str(tree.root.label) == "\U0001f4e6 (8) Coding"

    async def test_project_node_exists(self, app):
        async with app.run_test():
            tree = app.query_one("#workspaces-tree")
            project_nodes = [
                n for n in tree.root.children if n.allow_expand
            ]
            assert len(project_nodes) == 1
            assert str(project_nodes[0].label) == "\U0001f5c2\ufe0f (4) apr-api"

    async def test_ungrouped_tasks_under_project(self, app):
        async with app.run_test():
            tree = app.query_one("#workspaces-tree")
            proj_node = [n for n in tree.root.children if n.allow_expand][0]
            task_leaves = [n for n in proj_node.children if not n.allow_expand]
            assert len(task_leaves) == 4
            titles = {str(n.label) for n in task_leaves}
            assert "\U0001f4dd 1: Design API schema" in titles
            assert "\U0001f4dd 2: Endpoint design" in titles

    async def test_unassigned_tasks_after_projects(self, app):
        async with app.run_test():
            tree = app.query_one("#workspaces-tree")
            children = list(tree.root.children)
            # First child is the project node, rest are unassigned task leaves
            assert children[0].allow_expand
            unassigned = [n for n in children if not n.allow_expand]
            assert len(unassigned) == 4

    async def test_node_data_attached(self, app):
        async with app.run_test():
            tree = app.query_one("#workspaces-tree")
            proj_node = [n for n in tree.root.children if n.allow_expand][0]
            assert isinstance(proj_node.data, Project)
            task_leaf = [n for n in proj_node.children if not n.allow_expand][0]
            assert isinstance(task_leaf.data, Task)


class TestTreeReload:
    @pytest.fixture
    def app(self, seeded_tui_db):
        db_path, ids = seeded_tui_db
        return StickyNotesApp(db_path=db_path)

    async def test_reload_is_idempotent(self, app, seeded_tui_db):
        db_path, ids = seeded_tui_db
        async with app.run_test():
            tree = app.query_one("#workspaces-tree")
            first_count = len(list(tree.root.children))
            # Reload with same model
            from sticky_notes.tui.model import load_workspace_model
            conn = app.conn
            ws_id = ids["workspace_id"]
            model = load_workspace_model(conn, ws_id)
            tree.load(model)
            second_count = len(list(tree.root.children))
            assert first_count == second_count


class TestTreeNoActiveWorkspace:
    async def test_no_workspace_shows_message(self, tmp_path):
        db_path = tmp_path / "empty.db"
        conn = get_connection(db_path)
        init_db(conn)
        conn.close()
        app = StickyNotesApp(db_path=db_path)
        async with app.run_test():
            tree = app.query_one("#workspaces-tree")
            assert str(tree.root.label) == "No active workspace"


class TestTreeWithGroups:
    @pytest.fixture
    def grouped_tui_db(self, tmp_path):
        db_path = tmp_path / "grouped.db"
        conn = get_connection(db_path)
        init_db(conn)
        ws = service.create_workspace(conn, "Grouped")
        status = service.create_status(conn, ws.id, "Todo")
        proj = service.create_project(conn, ws.id, "myproj")
        parent_grp = service.create_group(conn, proj.id, "parent-group")
        child_grp = service.create_group(
            conn, proj.id, "child-group", parent_id=parent_grp.id
        )
        # Task in child group
        t1 = service.create_task(conn, ws.id, "grouped-task", status.id, project_id=proj.id)
        service.assign_task_to_group(conn, t1.id, child_grp.id, source="test")
        # Ungrouped task in project
        service.create_task(conn, ws.id, "ungrouped-task", status.id, project_id=proj.id)
        set_active_workspace_id(db_path, ws.id)
        conn.close()
        return db_path

    async def test_group_nodes_before_ungrouped(self, grouped_tui_db):
        app = StickyNotesApp(db_path=grouped_tui_db)
        async with app.run_test():
            tree = app.query_one("#workspaces-tree")
            proj_node = tree.root.children[0]
            children = list(proj_node.children)
            # First child is group node (expandable), last is ungrouped task leaf
            assert children[0].allow_expand
            assert isinstance(children[0].data, Group)
            assert not children[-1].allow_expand
            assert isinstance(children[-1].data, Task)

    async def test_nested_groups(self, grouped_tui_db):
        app = StickyNotesApp(db_path=grouped_tui_db)
        async with app.run_test():
            tree = app.query_one("#workspaces-tree")
            proj_node = tree.root.children[0]
            parent_node = [n for n in proj_node.children if n.allow_expand][0]
            assert str(parent_node.label) == "\U0001f4c1 (1) parent-group"
            child_nodes = list(parent_node.children)
            assert len(child_nodes) == 1
            assert str(child_nodes[0].label) == "\U0001f4c1 (1) child-group"
            # Task is under child group
            task_leaves = list(child_nodes[0].children)
            assert len(task_leaves) == 1
            assert not task_leaves[0].allow_expand


class TestKanbanColumns:
    @pytest.fixture
    def app(self, seeded_tui_db):
        db_path, ids = seeded_tui_db
        return StickyNotesApp(db_path=db_path), ids

    async def test_status_columns_rendered(self, app):
        app, ids = app
        async with app.run_test():
            cols = app.query(".status-col")
            assert len(cols) == 3

    async def test_column_has_title_with_count(self, app):
        app, ids = app
        async with app.run_test():
            titles = app.query(".status-col-title")
            title_texts = {str(t.render()) for t in titles}
            # Seed: Todo=4, In Progress=2, Done=2
            assert "Todo (4)" in title_texts
            assert "In Progress (2)" in title_texts
            assert "Done (2)" in title_texts

    async def test_tasks_in_correct_columns(self, app):
        app, ids = app
        async with app.run_test():
            done_col = app.query_one(
                f"#status-col-{ids['status_ids']['done']}"
            )
            cards = done_col.query(".task-card")
            card_texts = {str(c.render()) for c in cards}
            assert "6: Setup CI pipeline" in card_texts
            assert "8: Scaffold project" in card_texts

    async def test_task_cards_are_focusable(self, app):
        app, ids = app
        async with app.run_test():
            cards = app.query(".task-card")
            assert len(cards) > 0
            for card in cards:
                assert isinstance(card, TaskCard)
                assert card.can_focus is True

    async def test_task_cards_carry_task_data(self, app):
        app, ids = app
        async with app.run_test():
            cards = app.query(".task-card")
            for card in cards:
                assert isinstance(card.task_data, Task)
                assert card.task_data.id > 0

    async def test_no_workspace_no_columns(self, tmp_path):
        db_path = tmp_path / "empty.db"
        conn = get_connection(db_path)
        init_db(conn)
        conn.close()
        app = StickyNotesApp(db_path=db_path)
        async with app.run_test():
            cols = app.query(".status-col")
            assert len(cols) == 0
