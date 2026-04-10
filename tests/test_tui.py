from __future__ import annotations

from pathlib import Path

import pytest

from sticky_notes import service
from sticky_notes.active_workspace import set_active_workspace_id
from sticky_notes.connection import get_connection, init_db
from sticky_notes.models import Group, Project, Task, Workspace
from sticky_notes.tui.app import StickyNotesApp
from sticky_notes.tui.config import TuiConfig
from sticky_notes.tui.screens import TaskMetadataModal
from sticky_notes.tui.widgets import KanbanBoard, TaskCard


class TestTreePopulation:
    @pytest.fixture
    def app(self, seeded_tui_db):
        db_path, ids = seeded_tui_db
        return StickyNotesApp(db_path=db_path, config=TuiConfig())

    async def test_root_label_is_workspaces(self, app):
        async with app.run_test():
            tree = app.query_one("#workspaces-tree")
            assert str(tree.root.label) == "Workspaces"

    async def test_workspace_node_exists(self, app):
        async with app.run_test():
            tree = app.query_one("#workspaces-tree")
            ws_nodes = list(tree.root.children)
            assert len(ws_nodes) == 1
            assert str(ws_nodes[0].label) == "\U0001f4e6 (8) Coding"

    async def test_project_node_exists(self, app):
        async with app.run_test():
            tree = app.query_one("#workspaces-tree")
            ws_node = tree.root.children[0]
            project_nodes = [
                n for n in ws_node.children if n.allow_expand
            ]
            assert len(project_nodes) == 1
            assert str(project_nodes[0].label) == "\U0001f5c2\ufe0f (4) apr-api"

    async def test_ungrouped_tasks_under_project(self, app):
        async with app.run_test():
            tree = app.query_one("#workspaces-tree")
            ws_node = tree.root.children[0]
            proj_node = [n for n in ws_node.children if n.allow_expand][0]
            task_leaves = [n for n in proj_node.children if not n.allow_expand]
            assert len(task_leaves) == 4
            titles = {str(n.label) for n in task_leaves}
            assert "\U0001f4dd 1: Design API schema" in titles
            assert "\U0001f4dd 2: Endpoint design" in titles

    async def test_unassigned_tasks_after_projects(self, app):
        async with app.run_test():
            tree = app.query_one("#workspaces-tree")
            ws_node = tree.root.children[0]
            children = list(ws_node.children)
            # First child is the project node, rest are unassigned task leaves
            assert children[0].allow_expand
            unassigned = [n for n in children if not n.allow_expand]
            assert len(unassigned) == 4

    async def test_node_data_attached(self, app):
        async with app.run_test():
            tree = app.query_one("#workspaces-tree")
            ws_node = tree.root.children[0]
            proj_node = [n for n in ws_node.children if n.allow_expand][0]
            assert isinstance(proj_node.data, Project)
            task_leaf = [n for n in proj_node.children if not n.allow_expand][0]
            assert isinstance(task_leaf.data, Task)


class TestTreeReload:
    @pytest.fixture
    def app(self, seeded_tui_db):
        db_path, ids = seeded_tui_db
        return StickyNotesApp(db_path=db_path, config=TuiConfig())

    async def test_reload_is_idempotent(self, app, seeded_tui_db):
        db_path, ids = seeded_tui_db
        async with app.run_test():
            tree = app.query_one("#workspaces-tree")
            ws_node = tree.root.children[0]
            first_count = len(list(ws_node.children))
            # Reload with same models dict
            tree.load(app._models, expand_workspace_id=ids["workspace_id"])
            ws_node = tree.root.children[0]
            second_count = len(list(ws_node.children))
            assert first_count == second_count


class TestTreeNoWorkspaces:
    async def test_no_workspace_shows_message(self, tmp_path):
        db_path = tmp_path / "empty.db"
        conn = get_connection(db_path)
        init_db(conn)
        conn.close()
        app = StickyNotesApp(db_path=db_path, config=TuiConfig())
        async with app.run_test():
            tree = app.query_one("#workspaces-tree")
            assert str(tree.root.label) == "No workspaces"

    async def test_broken_workspace_skipped(self, tmp_path, monkeypatch):
        """A workspace that fails to load shouldn't crash the TUI."""
        db_path = tmp_path / "mixed.db"
        conn = get_connection(db_path)
        init_db(conn)
        good = service.create_workspace(conn, "Good")
        service.create_status(conn, good.id, "Todo")
        bad = service.create_workspace(conn, "Bad")
        set_active_workspace_id(db_path, good.id)
        conn.close()

        from sticky_notes.tui import model as tui_model
        _real = tui_model.load_workspace_model

        def _failing_load(conn, workspace_id):
            if workspace_id == bad.id:
                raise LookupError("corrupt")
            return _real(conn, workspace_id)

        monkeypatch.setattr(tui_model, "load_workspace_model", _failing_load)
        # Also patch the import in app.py
        from sticky_notes.tui import app as tui_app
        monkeypatch.setattr(tui_app, "load_workspace_model", _failing_load)

        app = StickyNotesApp(db_path=db_path, config=TuiConfig())
        async with app.run_test():
            tree = app.query_one("#workspaces-tree")
            ws_nodes = list(tree.root.children)
            assert len(ws_nodes) == 1
            assert str(ws_nodes[0].label).endswith("Good")


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
        app = StickyNotesApp(db_path=grouped_tui_db, config=TuiConfig())
        async with app.run_test():
            tree = app.query_one("#workspaces-tree")
            ws_node = tree.root.children[0]
            proj_node = ws_node.children[0]
            children = list(proj_node.children)
            # First child is group node (expandable), last is ungrouped task leaf
            assert children[0].allow_expand
            assert isinstance(children[0].data, Group)
            assert not children[-1].allow_expand
            assert isinstance(children[-1].data, Task)

    async def test_nested_groups(self, grouped_tui_db):
        app = StickyNotesApp(db_path=grouped_tui_db, config=TuiConfig())
        async with app.run_test():
            tree = app.query_one("#workspaces-tree")
            ws_node = tree.root.children[0]
            proj_node = ws_node.children[0]
            parent_node = [n for n in proj_node.children if n.allow_expand][0]
            assert str(parent_node.label) == "\U0001f4c1 (1) parent-group"
            child_nodes = list(parent_node.children)
            assert len(child_nodes) == 1
            assert str(child_nodes[0].label) == "\U0001f4c1 (1) child-group"
            # Task is under child group
            task_leaves = list(child_nodes[0].children)
            assert len(task_leaves) == 1
            assert not task_leaves[0].allow_expand

    async def test_refresh_preserves_expanded_group(self, grouped_tui_db):
        app = StickyNotesApp(db_path=grouped_tui_db, config=TuiConfig())
        async with app.run_test() as pilot:
            tree = app.query_one("#workspaces-tree")
            ws_node = tree.root.children[0]
            proj_node = ws_node.children[0]
            parent_node = [n for n in proj_node.children if n.allow_expand][0]
            # Expand the group
            parent_node.expand()
            assert parent_node.is_expanded
            # Trigger refresh
            app.action_refresh()
            await pilot.pause()
            await pilot.pause()
            # Group should still be expanded after rebuild
            ws_node = tree.root.children[0]
            proj_node = ws_node.children[0]
            parent_node = [n for n in proj_node.children if n.allow_expand][0]
            assert parent_node.is_expanded

    async def test_refresh_preserves_collapsed_project(self, grouped_tui_db):
        app = StickyNotesApp(db_path=grouped_tui_db, config=TuiConfig())
        async with app.run_test() as pilot:
            tree = app.query_one("#workspaces-tree")
            ws_node = tree.root.children[0]
            proj_node = ws_node.children[0]
            # Project starts expanded on first load
            assert proj_node.is_expanded
            # Collapse it
            proj_node.collapse()
            assert not proj_node.is_expanded
            # Trigger refresh
            app.action_refresh()
            await pilot.pause()
            await pilot.pause()
            # Project should still be collapsed
            ws_node = tree.root.children[0]
            proj_node = ws_node.children[0]
            assert not proj_node.is_expanded


class TestKanbanColumns:
    @pytest.fixture
    def app(self, seeded_tui_db):
        db_path, ids = seeded_tui_db
        return StickyNotesApp(db_path=db_path, config=TuiConfig()), ids

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
            assert "(4) Todo" in title_texts
            assert "(2) In Progress" in title_texts
            assert "(2) Done" in title_texts

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

    async def test_no_workspaces_no_columns(self, tmp_path):
        db_path = tmp_path / "empty.db"
        conn = get_connection(db_path)
        init_db(conn)
        conn.close()
        app = StickyNotesApp(db_path=db_path, config=TuiConfig())
        async with app.run_test():
            cols = app.query(".status-col")
            assert len(cols) == 0


class TestStatusMove:
    """Tests for shift+arrow / shift+ijkl task status movement."""

    @pytest.fixture
    def app(self, seeded_tui_db):
        db_path, ids = seeded_tui_db
        sids = ids["status_ids"]
        config = TuiConfig(status_order={
            ids["workspace_id"]: [sids["todo"], sids["in_progress"], sids["done"]],
        })
        return StickyNotesApp(db_path=db_path, config=config), ids

    def _col_title(self, app, status_id: int) -> str:
        col = app.query_one(f"#status-col-{status_id}")
        return str(col.query_one(".status-col-title").render())

    def _card_column_id(self, card: TaskCard) -> str:
        """Walk up to the .status-col ancestor to find which column a card is in."""
        node = card.parent
        while node is not None:
            if hasattr(node, "id") and node.id and node.id.startswith("status-col-"):
                return node.id
            node = node.parent
        raise AssertionError("Card not inside a status column")

    async def test_shift_right_moves_to_next_status(self, app):
        app, ids = app
        async with app.run_test() as pilot:
            # Focus a Todo card (task 1: Design API schema)
            todo_col = app.query_one(f"#status-col-{ids['status_ids']['todo']}")
            card = todo_col.query(TaskCard).first()
            app.set_focus(card)
            await pilot.pause()
            task_id = card.task_data.id

            await pilot.press("shift+right")
            await pilot.pause()
            await pilot.pause()

            # Card should now be in the In Progress column
            new_card = next(c for c in app.query(TaskCard) if c.task_data.id == task_id)
            assert self._card_column_id(new_card) == f"status-col-{ids['status_ids']['in_progress']}"

    async def test_shift_left_moves_to_previous_status(self, app):
        app, ids = app
        async with app.run_test() as pilot:
            ip_col = app.query_one(f"#status-col-{ids['status_ids']['in_progress']}")
            card = ip_col.query(TaskCard).first()
            app.set_focus(card)
            await pilot.pause()
            task_id = card.task_data.id

            await pilot.press("shift+left")
            await pilot.pause()
            await pilot.pause()

            new_card = next(c for c in app.query(TaskCard) if c.task_data.id == task_id)
            assert self._card_column_id(new_card) == f"status-col-{ids['status_ids']['todo']}"

    async def test_no_wrap_at_rightmost_column(self, app):
        app, ids = app
        async with app.run_test() as pilot:
            done_col = app.query_one(f"#status-col-{ids['status_ids']['done']}")
            card = done_col.query(TaskCard).first()
            app.set_focus(card)
            await pilot.pause()
            task_id = card.task_data.id

            await pilot.press("shift+right")
            await pilot.pause()
            await pilot.pause()

            # Card should still be in Done
            new_card = next(c for c in app.query(TaskCard) if c.task_data.id == task_id)
            assert self._card_column_id(new_card) == f"status-col-{ids['status_ids']['done']}"

    async def test_no_wrap_at_leftmost_column(self, app):
        app, ids = app
        async with app.run_test() as pilot:
            todo_col = app.query_one(f"#status-col-{ids['status_ids']['todo']}")
            card = todo_col.query(TaskCard).first()
            app.set_focus(card)
            await pilot.pause()
            task_id = card.task_data.id

            await pilot.press("shift+left")
            await pilot.pause()
            await pilot.pause()

            new_card = next(c for c in app.query(TaskCard) if c.task_data.id == task_id)
            assert self._card_column_id(new_card) == f"status-col-{ids['status_ids']['todo']}"

    async def test_bracket_right_alias(self, app):
        app, ids = app
        async with app.run_test() as pilot:
            todo_col = app.query_one(f"#status-col-{ids['status_ids']['todo']}")
            card = todo_col.query(TaskCard).first()
            app.set_focus(card)
            await pilot.pause()
            task_id = card.task_data.id

            await pilot.press("]")
            await pilot.pause()
            await pilot.pause()

            new_card = next(c for c in app.query(TaskCard) if c.task_data.id == task_id)
            assert self._card_column_id(new_card) == f"status-col-{ids['status_ids']['in_progress']}"

    async def test_bracket_left_alias(self, app):
        app, ids = app
        async with app.run_test() as pilot:
            ip_col = app.query_one(f"#status-col-{ids['status_ids']['in_progress']}")
            card = ip_col.query(TaskCard).first()
            app.set_focus(card)
            await pilot.pause()
            task_id = card.task_data.id

            await pilot.press("[")
            await pilot.pause()
            await pilot.pause()

            new_card = next(c for c in app.query(TaskCard) if c.task_data.id == task_id)
            assert self._card_column_id(new_card) == f"status-col-{ids['status_ids']['todo']}"

    async def test_column_titles_update_after_move(self, app):
        app, ids = app
        async with app.run_test() as pilot:
            todo_id = ids["status_ids"]["todo"]
            ip_id = ids["status_ids"]["in_progress"]

            assert self._col_title(app, todo_id) == "(4) Todo"
            assert self._col_title(app, ip_id) == "(2) In Progress"

            todo_col = app.query_one(f"#status-col-{todo_id}")
            card = todo_col.query(TaskCard).first()
            app.set_focus(card)
            await pilot.pause()

            await pilot.press("shift+right")
            await pilot.pause()
            await pilot.pause()

            assert self._col_title(app, todo_id) == "(3) Todo"
            assert self._col_title(app, ip_id) == "(3) In Progress"

    async def test_model_consistent_after_move(self, app):
        app, ids = app
        async with app.run_test() as pilot:
            todo_col = app.query_one(f"#status-col-{ids['status_ids']['todo']}")
            card = todo_col.query(TaskCard).first()
            app.set_focus(card)
            await pilot.pause()
            task_id = card.task_data.id

            await pilot.press("shift+right")
            await pilot.pause()
            await pilot.pause()

            # Model should reflect the new status
            model_task = next(t for t in app._active_model.all_tasks if t.id == task_id)
            assert model_task.status_id == ids["status_ids"]["in_progress"]

            # Card task_data should also be current
            new_card = next(c for c in app.query(TaskCard) if c.task_data.id == task_id)
            assert new_card.task_data.status_id == ids["status_ids"]["in_progress"]


class TestMultiWorkspaceTree:
    @pytest.fixture
    def app(self, multi_workspace_tui_db):
        db_path, ids = multi_workspace_tui_db
        return StickyNotesApp(db_path=db_path, config=TuiConfig()), ids

    async def test_root_has_two_workspace_children(self, app):
        app, ids = app
        async with app.run_test():
            tree = app.query_one("#workspaces-tree")
            ws_nodes = list(tree.root.children)
            assert len(ws_nodes) == 2
            for node in ws_nodes:
                assert node.allow_expand
                assert isinstance(node.data, Workspace)

    async def test_initial_workspace_expanded(self, app):
        app, ids = app
        async with app.run_test():
            tree = app.query_one("#workspaces-tree")
            ws_nodes = list(tree.root.children)
            # First workspace (Coding) pointed to by active-workspace file
            assert ws_nodes[0].is_expanded
            assert not ws_nodes[1].is_expanded

    async def test_workspace_labels_include_task_counts(self, app):
        app, ids = app
        async with app.run_test():
            tree = app.query_one("#workspaces-tree")
            labels = {str(n.label) for n in tree.root.children}
            assert "\U0001f4e6 (8) Coding" in labels
            assert "\U0001f4e6 (2) Personal" in labels

    async def test_navigate_to_second_workspace_switches_kanban(self, app):
        app, ids = app
        async with app.run_test() as pilot:
            ws2_id = ids["ws2"]["workspace_id"]
            # Initially kanban shows workspace 1
            assert app._active_workspace_id == ids["ws1"]["workspace_id"]
            # Navigate tree to workspace 2 node
            tree = app.query_one("#workspaces-tree")
            ws_nodes = list(tree.root.children)
            tree.select_node(ws_nodes[1])
            await pilot.pause()
            await pilot.pause()
            # Kanban should now show workspace 2
            assert app._active_workspace_id == ws2_id
            cols = app.query(".status-col")
            assert len(cols) == 2  # Backlog + Complete

    async def test_workspace_switch_preserves_other_expand_state(self, app):
        app, ids = app
        async with app.run_test() as pilot:
            tree = app.query_one("#workspaces-tree")
            ws1_node = tree.root.children[0]
            # ws1 project should be expanded on first load
            proj_node = ws1_node.children[0]
            assert proj_node.is_expanded
            # Navigate to ws2
            ws2_node = tree.root.children[1]
            tree.select_node(ws2_node)
            await pilot.pause()
            await pilot.pause()
            # Navigate back to ws1
            ws1_node = tree.root.children[0]
            tree.select_node(ws1_node)
            await pilot.pause()
            await pilot.pause()
            # ws1 project should still be expanded
            ws1_node = tree.root.children[0]
            proj_node = ws1_node.children[0]
            assert proj_node.is_expanded


class TestRefreshWorkspaceReconciliation:
    """Tests that refresh picks up new workspaces and drops archived ones."""

    async def test_refresh_picks_up_new_workspace(self, seeded_tui_db):
        db_path, ids = seeded_tui_db
        app = StickyNotesApp(db_path=db_path, config=TuiConfig())
        async with app.run_test() as pilot:
            tree = app.query_one("#workspaces-tree")
            assert len(tree.root.children) == 1
            # Create a second workspace via service (simulating CLI)
            service.create_workspace(app.conn, "Second")
            app.action_refresh()
            await pilot.pause()
            await pilot.pause()
            assert len(tree.root.children) == 2

    async def test_refresh_removes_archived_workspace(self, tmp_path):
        db_path = tmp_path / "two-ws.db"
        conn = get_connection(db_path)
        init_db(conn)
        ws1 = service.create_workspace(conn, "First")
        service.create_status(conn, ws1.id, "Todo")
        ws2 = service.create_workspace(conn, "Second")
        service.create_status(conn, ws2.id, "Todo")
        conn.close()
        app = StickyNotesApp(db_path=db_path, config=TuiConfig())
        async with app.run_test() as pilot:
            tree = app.query_one("#workspaces-tree")
            assert len(tree.root.children) == 2
            # Archive ws2 via the real cascade path (matches what CLI does)
            service.cascade_archive_workspace(app.conn, ws2.id, source="test")
            app.action_refresh()
            await pilot.pause()
            await pilot.pause()
            assert len(tree.root.children) == 1
            assert tree.root.children[0].data.id == ws1.id

    async def test_refresh_fallback_when_active_archived(self, tmp_path):
        db_path = tmp_path / "fallback.db"
        conn = get_connection(db_path)
        init_db(conn)
        ws1 = service.create_workspace(conn, "First")
        service.create_status(conn, ws1.id, "Todo")
        ws2 = service.create_workspace(conn, "Second")
        service.create_status(conn, ws2.id, "Todo")
        conn.close()
        app = StickyNotesApp(db_path=db_path, config=TuiConfig())
        async with app.run_test() as pilot:
            # Make ws2 active
            app._active_workspace_id = ws2.id
            # Archive ws2 via the real cascade path
            service.cascade_archive_workspace(app.conn, ws2.id, source="test")
            app.action_refresh()
            await pilot.pause()
            await pilot.pause()
            # Should fall back to ws1
            assert app._active_workspace_id == ws1.id


class TestMetadataKeybinding:
    @pytest.fixture
    def app(self, seeded_tui_db):
        db_path, ids = seeded_tui_db
        return StickyNotesApp(db_path=db_path, config=TuiConfig()), ids

    async def test_m_on_task_card_opens_metadata_modal(self, app):
        app, ids = app
        async with app.run_test() as pilot:
            card = app.query(TaskCard).first()
            app.set_focus(card)
            await pilot.pause()
            await pilot.press("m")
            await pilot.pause()
            assert isinstance(app.screen, TaskMetadataModal)
            assert app.screen.detail.id == card.task_data.id

    async def test_m_on_tree_task_opens_metadata_modal(self, app):
        app, ids = app
        async with app.run_test() as pilot:
            tree = app.query_one("#workspaces-tree")
            ws_node = tree.root.children[0]
            proj_node = [n for n in ws_node.children if n.allow_expand][0]
            task_leaf = [n for n in proj_node.children if not n.allow_expand][0]
            tree.select_node(task_leaf)
            app.set_focus(tree)
            await pilot.pause()
            await pilot.press("m")
            await pilot.pause()
            assert isinstance(app.screen, TaskMetadataModal)
            assert app.screen.detail.id == task_leaf.data.id

    async def test_m_on_project_tree_node_noop(self, app):
        app, ids = app
        async with app.run_test() as pilot:
            tree = app.query_one("#workspaces-tree")
            ws_node = tree.root.children[0]
            proj_node = [n for n in ws_node.children if n.allow_expand][0]
            tree.select_node(proj_node)
            app.set_focus(tree)
            await pilot.pause()
            stack_before = len(app.screen_stack)
            await pilot.press("m")
            await pilot.pause()
            assert len(app.screen_stack) == stack_before
            assert not isinstance(app.screen, TaskMetadataModal)

    async def test_metadata_save_persists_via_service(self, app):
        app, ids = app
        async with app.run_test() as pilot:
            card = app.query(TaskCard).first()
            task_id = card.task_data.id
            app.set_focus(card)
            await pilot.pause()
            await pilot.press("m")
            await pilot.pause()
            modal = app.screen
            assert isinstance(modal, TaskMetadataModal)
            # Fill the pre-populated blank row
            from textual.widgets import Input
            row = modal.query(".metadata-row").first()
            row.query_one(".metadata-key", Input).value = "assignee"
            row.query_one(".metadata-value", Input).value = "alice"
            modal.action_save()
            await pilot.pause()
            await pilot.pause()
            stored = service.get_task(app.conn, task_id)
            assert stored.metadata == {"assignee": "alice"}
            assert len(app.query_one("#workspaces-tree").root.children) == 1
