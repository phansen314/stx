"""Integration tests for hook wiring in service.py task mutations (task 158)."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

from stx import service
from stx.hooks import HookEvent
from stx.service import _determine_task_events


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _ws_status(conn: sqlite3.Connection, ws_name: str = "ws", st_name: str = "todo"):
    ws = service.create_workspace(conn, ws_name)
    st = service.create_status(conn, ws.id, st_name)
    return ws, st


def _task(conn: sqlite3.Connection, ws_id: int, status_id: int, title: str = "task A"):
    return service.create_task(conn, ws_id, title, status_id)


# ---------------------------------------------------------------------------
# _determine_task_events unit tests
# ---------------------------------------------------------------------------

class TestDetermineTaskEvents:
    def test_status_change_gives_moved(self) -> None:
        events = _determine_task_events({"status_id": {"old": 1, "new": 2}})
        assert events == [HookEvent.TASK_MOVED]

    def test_done_true_gives_done(self) -> None:
        events = _determine_task_events({"done": {"old": False, "new": True}})
        assert events == [HookEvent.TASK_DONE]

    def test_done_false_gives_undone(self) -> None:
        events = _determine_task_events({"done": {"old": True, "new": False}})
        assert events == [HookEvent.TASK_UNDONE]

    def test_group_set_gives_assigned(self) -> None:
        events = _determine_task_events({"group_id": {"old": None, "new": 5}})
        assert events == [HookEvent.TASK_ASSIGNED]

    def test_group_cleared_gives_unassigned(self) -> None:
        events = _determine_task_events({"group_id": {"old": 5, "new": None}})
        assert events == [HookEvent.TASK_UNASSIGNED]

    def test_title_change_gives_updated(self) -> None:
        events = _determine_task_events({"title": {"old": "a", "new": "b"}})
        assert events == [HookEvent.TASK_UPDATED]

    def test_status_and_title_gives_moved_and_updated(self) -> None:
        events = _determine_task_events({
            "status_id": {"old": 1, "new": 2},
            "title": {"old": "a", "new": "b"},
        })
        assert HookEvent.TASK_MOVED in events
        assert HookEvent.TASK_UPDATED in events

    def test_empty_changes_returns_empty(self) -> None:
        assert _determine_task_events({}) == []


# ---------------------------------------------------------------------------
# create_task hooks
# ---------------------------------------------------------------------------

class TestCreateTaskHooks:
    def test_post_hook_fires_with_entity(self, conn: sqlite3.Connection) -> None:
        ws, st = _ws_status(conn)
        post_calls = []

        def fake_fire(event, **kwargs):
            if event == HookEvent.TASK_CREATED:
                post_calls.append(kwargs)

        with patch("stx.service.fire_hooks", side_effect=fake_fire):
            task = service.create_task(conn, ws.id, "mytask", st.id)

        assert len(post_calls) == 1
        entity = post_calls[0]["entity"]
        assert entity is not None
        assert entity.id == task.id
        assert entity.title == "mytask"


# ---------------------------------------------------------------------------
# update_task hooks — event selection
# ---------------------------------------------------------------------------

class TestUpdateTaskHooks:
    def test_status_change_fires_moved(self, conn: sqlite3.Connection) -> None:
        ws, st = _ws_status(conn)
        st2 = service.create_status(conn, ws.id, "done")
        task = _task(conn, ws.id, st.id)
        fired = []
        with patch("stx.service.fire_hooks", side_effect=lambda e, **kw: fired.append(e)):
            service.update_task(conn, task.id, {"status_id": st2.id}, "test")
        events = fired
        assert HookEvent.TASK_MOVED in events

    def test_done_true_fires_task_done(self, conn: sqlite3.Connection) -> None:
        ws, st = _ws_status(conn)
        task = _task(conn, ws.id, st.id)
        fired = []
        with patch("stx.service.fire_hooks", side_effect=lambda e, **kw: fired.append(e)):
            service.update_task(conn, task.id, {"done": True}, "test")
        events = fired
        assert HookEvent.TASK_DONE in events

    def test_done_false_fires_task_undone(self, conn: sqlite3.Connection) -> None:
        ws, st = _ws_status(conn)
        task = _task(conn, ws.id, st.id)
        service.update_task(conn, task.id, {"done": True}, "test")
        fired = []
        with patch("stx.service.fire_hooks", side_effect=lambda e, **kw: fired.append(e)):
            service.update_task(conn, task.id, {"done": False}, "test")
        events = fired
        assert HookEvent.TASK_UNDONE in events

    def test_title_change_fires_updated(self, conn: sqlite3.Connection) -> None:
        ws, st = _ws_status(conn)
        task = _task(conn, ws.id, st.id)
        fired = []
        with patch("stx.service.fire_hooks", side_effect=lambda e, **kw: fired.append(e)):
            service.update_task(conn, task.id, {"title": "new title"}, "test")
        events = fired
        assert HookEvent.TASK_UPDATED in events

    def test_terminal_status_fires_moved_and_done_post(
        self, conn: sqlite3.Connection
    ) -> None:
        ws, st = _ws_status(conn)
        terminal_st = service.create_status(conn, ws.id, "done")
        service.update_status(conn, terminal_st.id, {"is_terminal": True})
        task = _task(conn, ws.id, st.id)
        fired_post = []
        def fake_fire(event, **kw):
            fired_post.append(event)
        with patch("stx.service.fire_hooks", side_effect=fake_fire):
            service.update_task(conn, task.id, {"status_id": terminal_st.id}, "test")
        assert HookEvent.TASK_MOVED in fired_post
        assert HookEvent.TASK_DONE in fired_post


# ---------------------------------------------------------------------------
# archive_task hooks
# ---------------------------------------------------------------------------

class TestArchiveTaskHooks:
    def test_post_fires(self, conn: sqlite3.Connection) -> None:
        ws, st = _ws_status(conn)
        task = _task(conn, ws.id, st.id)
        fired = []
        with patch("stx.service.fire_hooks", side_effect=lambda e, **kw: fired.append(e)):
            service.archive_task(conn, task.id, source="test")
        assert HookEvent.TASK_ARCHIVED in fired


# ---------------------------------------------------------------------------
# move_task_to_workspace hooks
# ---------------------------------------------------------------------------

class TestTransferTaskHooks:
    def test_transferred_event_with_workspace_refs(
        self, conn: sqlite3.Connection
    ) -> None:
        ws1, st1 = _ws_status(conn, "src", "todo")
        ws2 = service.create_workspace(conn, "tgt")
        st2 = service.create_status(conn, ws2.id, "backlog")
        task = _task(conn, ws1.id, st1.id)
        post_kwargs = {}
        def fake_fire(event, **kw):
            if event == HookEvent.TASK_TRANSFERRED:
                post_kwargs.update(kw)
        with patch("stx.service.fire_hooks", side_effect=fake_fire):
            service.move_task_to_workspace(conn, task.id, ws2.id, st2.id, source="test")
        assert post_kwargs["source_workspace"] == {"id": ws1.id, "name": "src"}
        assert post_kwargs["target_workspace"] == {"id": ws2.id, "name": "tgt"}
        assert post_kwargs["changes"]["workspace_id"]["old"] == ws1.id
        assert post_kwargs["changes"]["workspace_id"]["new"] == ws2.id


# ---------------------------------------------------------------------------
# set_task_meta / remove_task_meta / replace_task_metadata hooks
# ---------------------------------------------------------------------------

class TestMetaHooks:
    def test_set_meta_fires(self, conn: sqlite3.Connection) -> None:
        ws, st = _ws_status(conn)
        task = _task(conn, ws.id, st.id)
        fired = []
        with patch("stx.service.fire_hooks", side_effect=lambda e, **kw: fired.append((e, kw))):
            service.set_task_meta(conn, task.id, "tag", "urgent")
        post = [(e, k) for e, k in fired]
        assert len(post) == 1 and post[0][0] == HookEvent.TASK_META_SET
        assert post[0][1]["meta_key"] == "tag"
        assert post[0][1]["meta_value"] == "urgent"

    def test_set_meta_no_hook_when_unchanged(self, conn: sqlite3.Connection) -> None:
        ws, st = _ws_status(conn)
        task = _task(conn, ws.id, st.id)
        service.set_task_meta(conn, task.id, "tag", "v")
        fired = []
        with patch("stx.service.fire_hooks", side_effect=lambda e, **kw: fired.append(e)):
            service.set_task_meta(conn, task.id, "tag", "v")  # same value
        assert fired == []

    def test_remove_meta_fires(self, conn: sqlite3.Connection) -> None:
        ws, st = _ws_status(conn)
        task = _task(conn, ws.id, st.id)
        service.set_task_meta(conn, task.id, "x", "1")
        fired = []
        with patch("stx.service.fire_hooks", side_effect=lambda e, **kw: fired.append(e)):
            service.remove_task_meta(conn, task.id, "x")
        assert HookEvent.TASK_META_REMOVED in fired

    def test_replace_metadata_fires_per_key(self, conn: sqlite3.Connection) -> None:
        ws, st = _ws_status(conn)
        task = _task(conn, ws.id, st.id)
        service.set_task_meta(conn, task.id, "a", "old")
        service.set_task_meta(conn, task.id, "b", "keep")
        fired = []
        with patch("stx.service.fire_hooks", side_effect=lambda e, **kw: fired.append((e, kw["meta_key"]))):
            service.replace_task_metadata(conn, task.id, {"a": "new", "c": "added"}, source="test")
        # key "a" changed, key "c" added (META_SET), key "b" removed (META_REMOVED)
        event_keys = [(e, k) for e, k in fired]
        assert (HookEvent.TASK_META_SET, "a") in event_keys
        assert (HookEvent.TASK_META_SET, "c") in event_keys
        assert (HookEvent.TASK_META_REMOVED, "b") in event_keys


# ---------------------------------------------------------------------------
# Review-158 fix tests
# ---------------------------------------------------------------------------

class TestCreateTaskTerminalStatus:
    """H2 fix: create into terminal status fires TASK_DONE post-hook."""

    def test_terminal_status_create_fires_task_done_post(
        self, conn: sqlite3.Connection
    ) -> None:
        ws, st = _ws_status(conn)
        service.update_status(conn, st.id, {"is_terminal": True})
        fired_post = []
        with patch("stx.service.fire_hooks", side_effect=lambda e, **kw: fired_post.append(e)):
            service.create_task(conn, ws.id, "done-on-arrival", st.id)
        assert HookEvent.TASK_CREATED in fired_post
        assert HookEvent.TASK_DONE in fired_post

    def test_non_terminal_status_create_no_task_done(
        self, conn: sqlite3.Connection
    ) -> None:
        ws, st = _ws_status(conn)
        fired_post = []
        with patch("stx.service.fire_hooks", side_effect=lambda e, **kw: fired_post.append(e)):
            service.create_task(conn, ws.id, "normal", st.id)
        assert HookEvent.TASK_CREATED in fired_post
        assert HookEvent.TASK_DONE not in fired_post


class TestUpdateTaskNoOpShortCircuit:
    """H3 fix: update_task with no real delta skips hooks and DB write."""

    def test_no_change_fires_no_hooks(self, conn: sqlite3.Connection) -> None:
        ws, st = _ws_status(conn)
        task = _task(conn, ws.id, st.id)
        fired = []
        with patch("stx.service.fire_hooks", side_effect=lambda e, **kw: fired.append(e)):
            service.update_task(conn, task.id, {"title": task.title}, "test")
        assert fired == []

    def test_no_change_preserves_version(self, conn: sqlite3.Connection) -> None:
        ws, st = _ws_status(conn)
        task = _task(conn, ws.id, st.id)
        result = service.update_task(conn, task.id, {"title": task.title}, "test")
        assert result.version == task.version


class TestReplaceMetadataNormalization:
    """C1 fix: replace_task_metadata passes normalized keys into _replace_entity_metadata."""

    def test_uppercase_input_keys_normalized_in_hook_events(
        self, conn: sqlite3.Connection
    ) -> None:
        ws, st = _ws_status(conn)
        task = _task(conn, ws.id, st.id)
        fired_keys = []
        with patch("stx.service.fire_hooks", side_effect=lambda e, **kw: fired_keys.append(kw["meta_key"])):
            service.replace_task_metadata(conn, task.id, {"FOO": "bar"}, source="test")
        assert "foo" in fired_keys
        assert "FOO" not in fired_keys


class TestWrapperEntryPoints:
    """M3: thin wrapper functions still fire the expected hook events."""

    def test_move_task_fires_moved(self, conn: sqlite3.Connection) -> None:
        ws, st = _ws_status(conn)
        st2 = service.create_status(conn, ws.id, "done")
        task = _task(conn, ws.id, st.id)
        fired = []
        with patch("stx.service.fire_hooks", side_effect=lambda e, **kw: fired.append(e)):
            service.move_task(conn, task.id, st2.id, "test")
        assert HookEvent.TASK_MOVED in fired

    def test_mark_task_done_fires_done(self, conn: sqlite3.Connection) -> None:
        ws, st = _ws_status(conn)
        task = _task(conn, ws.id, st.id)
        fired = []
        with patch("stx.service.fire_hooks", side_effect=lambda e, **kw: fired.append(e)):
            service.mark_task_done(conn, task.id, source="test")
        assert HookEvent.TASK_DONE in fired

    def test_mark_task_undone_fires_undone(self, conn: sqlite3.Connection) -> None:
        ws, st = _ws_status(conn)
        task = _task(conn, ws.id, st.id)
        service.mark_task_done(conn, task.id, source="test")
        fired = []
        with patch("stx.service.fire_hooks", side_effect=lambda e, **kw: fired.append(e)):
            service.mark_task_undone(conn, task.id, source="test")
        assert HookEvent.TASK_UNDONE in fired

    def test_assign_task_to_group_fires_assigned(self, conn: sqlite3.Connection) -> None:
        ws, st = _ws_status(conn)
        task = _task(conn, ws.id, st.id)
        grp = service.create_group(conn, ws.id, "grp")
        fired = []
        with patch("stx.service.fire_hooks", side_effect=lambda e, **kw: fired.append(e)):
            service.assign_task_to_group(conn, task.id, grp.id, source="test")
        assert HookEvent.TASK_ASSIGNED in fired

    def test_unassign_task_from_group_fires_unassigned(
        self, conn: sqlite3.Connection
    ) -> None:
        ws, st = _ws_status(conn)
        task = _task(conn, ws.id, st.id)
        grp = service.create_group(conn, ws.id, "grp")
        service.assign_task_to_group(conn, task.id, grp.id, source="test")
        fired = []
        with patch("stx.service.fire_hooks", side_effect=lambda e, **kw: fired.append(e)):
            service.unassign_task_from_group(conn, task.id, source="test")
        assert HookEvent.TASK_UNASSIGNED in fired


class TestIdempotencySkips:
    """M4: idempotent paths must not fire hooks."""

    def test_mark_done_already_done_fires_no_hooks(
        self, conn: sqlite3.Connection
    ) -> None:
        ws, st = _ws_status(conn)
        task = _task(conn, ws.id, st.id)
        service.mark_task_done(conn, task.id, source="test")
        fired = []
        with patch("stx.service.fire_hooks", side_effect=lambda e, **kw: fired.append(e)):
            service.mark_task_done(conn, task.id, source="test")
        assert fired == []

    def test_mark_undone_not_done_fires_no_hooks(
        self, conn: sqlite3.Connection
    ) -> None:
        ws, st = _ws_status(conn)
        task = _task(conn, ws.id, st.id)
        fired = []
        with patch("stx.service.fire_hooks", side_effect=lambda e, **kw: fired.append(e)):
            service.mark_task_undone(conn, task.id, source="test")
        assert fired == []

    def test_remove_meta_absent_key_fires_no_hooks(
        self, conn: sqlite3.Connection
    ) -> None:
        ws, st = _ws_status(conn)
        task = _task(conn, ws.id, st.id)
        fired = []
        with patch("stx.service.fire_hooks", side_effect=lambda e, **kw: fired.append(e)):
            with pytest.raises(LookupError):
                service.remove_task_meta(conn, task.id, "nonexistent")
        assert fired == []


# ---------------------------------------------------------------------------
# Task 160: group, workspace, status, and edge hook wiring
# ---------------------------------------------------------------------------

def _capture(calls: list) -> object:
    def fake(event, **kw):
        calls.append((event, kw))
    return fake


class TestWorkspaceHooks:
    def test_create_fires(self, conn: sqlite3.Connection) -> None:
        calls: list = []
        with patch("stx.service.fire_hooks", side_effect=_capture(calls)):
            ws = service.create_workspace(conn, "ws1")
        post = [c for c in calls if c[0] == HookEvent.WORKSPACE_CREATED]
        assert len(post) == 1 and post[0][1]["entity"] == ws
        assert post[0][1]["proposed"]["name"] == "ws1"

    def test_update_fires_updated_with_changes(self, conn: sqlite3.Connection) -> None:
        ws = service.create_workspace(conn, "ws1")
        calls: list = []
        with patch("stx.service.fire_hooks", side_effect=_capture(calls)):
            service.update_workspace(conn, ws.id, {"name": "ws2"}, "test")
        post = [c for c in calls if c[0] == HookEvent.WORKSPACE_UPDATED]
        assert len(post) == 1
        assert post[0][1]["changes"]["name"] == {"old": "ws1", "new": "ws2"}

    def test_update_no_op_fires_nothing(self, conn: sqlite3.Connection) -> None:
        ws = service.create_workspace(conn, "ws1")
        calls: list = []
        with patch("stx.service.fire_hooks", side_effect=_capture(calls)):
            service.update_workspace(conn, ws.id, {"name": "ws1"}, "test")
        assert calls == []

    def test_archive_fires(self, conn: sqlite3.Connection) -> None:
        ws = service.create_workspace(conn, "ws1")
        calls: list = []
        with patch("stx.service.fire_hooks", side_effect=_capture(calls)):
            service.cascade_archive_workspace(conn, ws.id, source="test")
        events = [e for e, _ in calls]
        assert events.count(HookEvent.WORKSPACE_ARCHIVED) == 1


class TestStatusHooks:
    def test_create_fires(self, conn: sqlite3.Connection) -> None:
        ws = service.create_workspace(conn, "ws")
        calls: list = []
        with patch("stx.service.fire_hooks", side_effect=_capture(calls)):
            st = service.create_status(conn, ws.id, "todo")
        post = [c for c in calls if c[0] == HookEvent.STATUS_CREATED]
        assert len(post) == 1 and post[0][1]["entity"].id == st.id
        assert post[0][1]["proposed"]["name"] == "todo"

    def test_update_fires_with_changes(self, conn: sqlite3.Connection) -> None:
        ws, st = _ws_status(conn)
        calls: list = []
        with patch("stx.service.fire_hooks", side_effect=_capture(calls)):
            service.update_status(conn, st.id, {"name": "backlog"}, "test")
        post = [c for c in calls if c[0] == HookEvent.STATUS_UPDATED]
        assert len(post) == 1
        assert post[0][1]["changes"]["name"]["new"] == "backlog"

    def test_archive_fires(self, conn: sqlite3.Connection) -> None:
        ws, st = _ws_status(conn)
        calls: list = []
        with patch("stx.service.fire_hooks", side_effect=_capture(calls)):
            service.archive_status(conn, st.id, source="test")
        events = [e for e, _ in calls]
        assert events.count(HookEvent.STATUS_ARCHIVED) == 1


class TestGroupHooks:
    def test_create_fires(self, conn: sqlite3.Connection) -> None:
        ws, _ = _ws_status(conn)
        calls: list = []
        with patch("stx.service.fire_hooks", side_effect=_capture(calls)):
            g = service.create_group(conn, ws.id, "grp", description="d")
        post = [c for c in calls if c[0] == HookEvent.GROUP_CREATED]
        assert len(post) == 1 and post[0][1]["entity"].id == g.id
        assert post[0][1]["proposed"]["title"] == "grp"

    def test_update_fires_with_changes(self, conn: sqlite3.Connection) -> None:
        ws, _ = _ws_status(conn)
        g = service.create_group(conn, ws.id, "grp")
        calls: list = []
        with patch("stx.service.fire_hooks", side_effect=_capture(calls)):
            service.update_group(conn, g.id, {"title": "grp2"}, "test")
        post = [c for c in calls if c[0] == HookEvent.GROUP_UPDATED]
        assert len(post) == 1
        assert post[0][1]["changes"]["title"]["new"] == "grp2"

    def test_cascade_archive_fires(self, conn: sqlite3.Connection) -> None:
        ws, _ = _ws_status(conn)
        g = service.create_group(conn, ws.id, "grp")
        calls: list = []
        with patch("stx.service.fire_hooks", side_effect=_capture(calls)):
            service.cascade_archive_group(conn, g.id, source="test")
        events = [e for e, _ in calls]
        assert events.count(HookEvent.GROUP_ARCHIVED) == 1

    def test_cascade_archive_skips_per_task_hooks(self, conn: sqlite3.Connection) -> None:
        """Carve-out: bulk-archived tasks in a cascade do NOT fire TASK_ARCHIVED."""
        ws, st = _ws_status(conn)
        g = service.create_group(conn, ws.id, "grp")
        service.create_task(conn, ws.id, "t1", st.id, group_id=g.id)
        service.create_task(conn, ws.id, "t2", st.id, group_id=g.id)
        calls: list = []
        with patch("stx.service.fire_hooks", side_effect=_capture(calls)):
            service.cascade_archive_group(conn, g.id, source="test")
        assert not any(e == HookEvent.TASK_ARCHIVED for e, _ in calls)

    def test_meta_set_fires(self, conn: sqlite3.Connection) -> None:
        ws, _ = _ws_status(conn)
        g = service.create_group(conn, ws.id, "grp")
        calls: list = []
        with patch("stx.service.fire_hooks", side_effect=_capture(calls)):
            service.set_group_meta(conn, g.id, "tag", "v")
        events = [e for e, _ in calls]
        assert events.count(HookEvent.GROUP_META_SET) == 1

    def test_meta_remove_fires(self, conn: sqlite3.Connection) -> None:
        ws, _ = _ws_status(conn)
        g = service.create_group(conn, ws.id, "grp")
        service.set_group_meta(conn, g.id, "tag", "v")
        calls: list = []
        with patch("stx.service.fire_hooks", side_effect=_capture(calls)):
            service.remove_group_meta(conn, g.id, "tag")
        events = [e for e, _ in calls]
        assert events.count(HookEvent.GROUP_META_REMOVED) == 1

    def test_replace_metadata_fires_per_key(self, conn: sqlite3.Connection) -> None:
        ws, _ = _ws_status(conn)
        g = service.create_group(conn, ws.id, "grp")
        service.set_group_meta(conn, g.id, "a", "old")
        service.set_group_meta(conn, g.id, "b", "keep")
        calls: list = []
        with patch("stx.service.fire_hooks", side_effect=_capture(calls)):
            service.replace_group_metadata(conn, g.id, {"a": "new", "c": "added"}, source="test")
        events_by_key = {(e, kw.get("meta_key")) for e, kw in calls}
        assert (HookEvent.GROUP_META_SET, "a") in events_by_key
        assert (HookEvent.GROUP_META_SET, "c") in events_by_key
        assert (HookEvent.GROUP_META_REMOVED, "b") in events_by_key


class TestWorkspaceMetaHooks:
    def test_set_meta_fires(self, conn: sqlite3.Connection) -> None:
        ws = service.create_workspace(conn, "ws")
        calls: list = []
        with patch("stx.service.fire_hooks", side_effect=_capture(calls)):
            service.set_workspace_meta(conn, ws.id, "tag", "v")
        events = [e for e, _ in calls]
        assert events.count(HookEvent.WORKSPACE_META_SET) == 1

    def test_remove_meta_fires(self, conn: sqlite3.Connection) -> None:
        ws = service.create_workspace(conn, "ws")
        service.set_workspace_meta(conn, ws.id, "tag", "v")
        calls: list = []
        with patch("stx.service.fire_hooks", side_effect=_capture(calls)):
            service.remove_workspace_meta(conn, ws.id, "tag")
        events = [e for e, _ in calls]
        assert events.count(HookEvent.WORKSPACE_META_REMOVED) == 1


class TestEdgeHooks:
    def test_create_fires(self, conn: sqlite3.Connection) -> None:
        ws, st = _ws_status(conn)
        t1 = _task(conn, ws.id, st.id, "t1")
        t2 = _task(conn, ws.id, st.id, "t2")
        calls: list = []
        with patch("stx.service.fire_hooks", side_effect=_capture(calls)):
            service.add_edge(conn, ("task", t1.id), ("task", t2.id), kind="blocks")
        post = [c for c in calls if c[0] == HookEvent.EDGE_CREATED]
        assert len(post) == 1
        assert post[0][1]["entity"]["from_id"] == t1.id
        assert post[0][1]["entity"]["to_id"] == t2.id
        assert post[0][1]["entity"]["archived"] is False

    def test_archive_fires(self, conn: sqlite3.Connection) -> None:
        ws, st = _ws_status(conn)
        t1 = _task(conn, ws.id, st.id, "t1")
        t2 = _task(conn, ws.id, st.id, "t2")
        service.add_edge(conn, ("task", t1.id), ("task", t2.id), kind="blocks")
        calls: list = []
        with patch("stx.service.fire_hooks", side_effect=_capture(calls)):
            service.archive_edge(conn, ("task", t1.id), ("task", t2.id), kind="blocks")
        events = [e for e, _ in calls]
        assert events.count(HookEvent.EDGE_ARCHIVED) == 1

    def test_update_fires_on_acyclic_flip(self, conn: sqlite3.Connection) -> None:
        ws, st = _ws_status(conn)
        t1 = _task(conn, ws.id, st.id, "t1")
        t2 = _task(conn, ws.id, st.id, "t2")
        service.add_edge(conn, ("task", t1.id), ("task", t2.id), kind="informs", acyclic=False)
        calls: list = []
        with patch("stx.service.fire_hooks", side_effect=_capture(calls)):
            service.update_edge(
                conn, ("task", t1.id), ("task", t2.id),
                kind="informs", changes={"acyclic": True}, source="test",
            )
        events = [e for e, _ in calls]
        assert events.count(HookEvent.EDGE_UPDATED) == 1

    def test_update_noop_skips_hooks(self, conn: sqlite3.Connection) -> None:
        ws, st = _ws_status(conn)
        t1 = _task(conn, ws.id, st.id, "t1")
        t2 = _task(conn, ws.id, st.id, "t2")
        service.add_edge(conn, ("task", t1.id), ("task", t2.id), kind="blocks", acyclic=True)
        calls: list = []
        with patch("stx.service.fire_hooks", side_effect=_capture(calls)):
            service.update_edge(
                conn, ("task", t1.id), ("task", t2.id),
                kind="blocks", changes={"acyclic": True}, source="test",
            )
        assert calls == []

    def test_meta_set_fires(self, conn: sqlite3.Connection) -> None:
        ws, st = _ws_status(conn)
        t1 = _task(conn, ws.id, st.id, "t1")
        t2 = _task(conn, ws.id, st.id, "t2")
        service.add_edge(conn, ("task", t1.id), ("task", t2.id), kind="blocks")
        calls: list = []
        with patch("stx.service.fire_hooks", side_effect=_capture(calls)):
            service.set_edge_meta(conn, "task", t1.id, "task", t2.id, "blocks", "tag", "v")
        events = [e for e, _ in calls]
        assert events.count(HookEvent.EDGE_META_SET) == 1

    def test_meta_remove_fires(self, conn: sqlite3.Connection) -> None:
        ws, st = _ws_status(conn)
        t1 = _task(conn, ws.id, st.id, "t1")
        t2 = _task(conn, ws.id, st.id, "t2")
        service.add_edge(conn, ("task", t1.id), ("task", t2.id), kind="blocks")
        service.set_edge_meta(conn, "task", t1.id, "task", t2.id, "blocks", "tag", "v")
        calls: list = []
        with patch("stx.service.fire_hooks", side_effect=_capture(calls)):
            service.remove_edge_meta(conn, "task", t1.id, "task", t2.id, "blocks", "tag")
        events = [e for e, _ in calls]
        assert events.count(HookEvent.EDGE_META_REMOVED) == 1

    def test_replace_metadata_fires_per_key(self, conn: sqlite3.Connection) -> None:
        ws, st = _ws_status(conn)
        t1 = _task(conn, ws.id, st.id, "t1")
        t2 = _task(conn, ws.id, st.id, "t2")
        service.add_edge(conn, ("task", t1.id), ("task", t2.id), kind="blocks")
        service.set_edge_meta(conn, "task", t1.id, "task", t2.id, "blocks", "a", "old")
        service.set_edge_meta(conn, "task", t1.id, "task", t2.id, "blocks", "b", "keep")
        calls: list = []
        with patch("stx.service.fire_hooks", side_effect=_capture(calls)):
            service.replace_edge_metadata(
                conn, "task", t1.id, "task", t2.id, "blocks",
                {"a": "new", "c": "added"}, source="test",
            )
        events_by_key = {(e, kw.get("meta_key")) for e, kw in calls}
        assert (HookEvent.EDGE_META_SET, "a") in events_by_key
        assert (HookEvent.EDGE_META_SET, "c") in events_by_key
        assert (HookEvent.EDGE_META_REMOVED, "b") in events_by_key

    def test_revival_fires_edge_updated_not_created(self, conn: sqlite3.Connection) -> None:
        ws, st = _ws_status(conn)
        t1 = _task(conn, ws.id, st.id, "t1")
        t2 = _task(conn, ws.id, st.id, "t2")
        service.add_edge(conn, ("task", t1.id), ("task", t2.id), kind="blocks")
        service.archive_edge(conn, ("task", t1.id), ("task", t2.id), kind="blocks")
        calls: list = []
        with patch("stx.service.fire_hooks", side_effect=_capture(calls)):
            service.add_edge(conn, ("task", t1.id), ("task", t2.id), kind="blocks")
        events = [e for e, _ in calls]
        assert HookEvent.EDGE_UPDATED in events
        assert HookEvent.EDGE_CREATED not in events
        updated = [kw for e, kw in calls if e == HookEvent.EDGE_UPDATED]
        assert updated[0]["changes"]["archived"] == {"old": True, "new": False}


# ---------------------------------------------------------------------------
# Task 160 review fixes — carve-out for workspace and idempotent archive.
# ---------------------------------------------------------------------------


class TestCascadeArchiveWorkspaceCarveOut:
    def test_skips_per_entity_hooks(self, conn: sqlite3.Connection) -> None:
        ws = service.create_workspace(conn, "ws")
        st = service.create_status(conn, ws.id, "todo")
        g = service.create_group(conn, ws.id, "grp")
        service.create_task(conn, ws.id, "t1", st.id, group_id=g.id)
        service.create_task(conn, ws.id, "t2", st.id)
        calls: list = []
        with patch("stx.service.fire_hooks", side_effect=_capture(calls)):
            service.cascade_archive_workspace(conn, ws.id, source="test")
        events = [e for e, _ in calls]
        # Only WORKSPACE_ARCHIVED (post only); no per-entity cascade hooks.
        assert HookEvent.TASK_ARCHIVED not in events
        assert HookEvent.GROUP_ARCHIVED not in events
        assert HookEvent.STATUS_ARCHIVED not in events
        assert events.count(HookEvent.WORKSPACE_ARCHIVED) == 1


class TestIdempotentArchivePayload:
    def test_workspace_second_archive_reports_old_true(
        self, conn: sqlite3.Connection
    ) -> None:
        ws = service.create_workspace(conn, "ws")
        service.cascade_archive_workspace(conn, ws.id, source="test")
        calls: list = []
        with patch("stx.service.fire_hooks", side_effect=_capture(calls)):
            service.cascade_archive_workspace(conn, ws.id, source="test")
        post_calls = [c for c in calls if c[0] == HookEvent.WORKSPACE_ARCHIVED]
        assert post_calls, "expected POST hook on repeat archive"
        assert post_calls[0][1]["changes"]["archived"]["old"] is True

    def test_group_second_archive_reports_old_true(
        self, conn: sqlite3.Connection
    ) -> None:
        ws, _ = _ws_status(conn)
        g = service.create_group(conn, ws.id, "grp")
        service.cascade_archive_group(conn, g.id, source="test")
        calls: list = []
        with patch("stx.service.fire_hooks", side_effect=_capture(calls)):
            service.cascade_archive_group(conn, g.id, source="test")
        post_calls = [c for c in calls if c[0] == HookEvent.GROUP_ARCHIVED]
        assert post_calls
        assert post_calls[0][1]["changes"]["archived"]["old"] is True

    def test_status_second_archive_reports_old_true(
        self, conn: sqlite3.Connection
    ) -> None:
        ws, st = _ws_status(conn)
        service.archive_status(conn, st.id, source="test")
        calls: list = []
        with patch("stx.service.fire_hooks", side_effect=_capture(calls)):
            service.archive_status(conn, st.id, source="test")
        post_calls = [c for c in calls if c[0] == HookEvent.STATUS_ARCHIVED]
        assert post_calls
        assert post_calls[0][1]["changes"]["archived"]["old"] is True


# ---------------------------------------------------------------------------
# Bulk archive payload fields (tasks 162, 165)
# ---------------------------------------------------------------------------

class TestBulkArchivePayloads:
    """archive_status / cascade_archive_group / cascade_archive_workspace
    emit affected ID lists in the payload; no per-task hooks fire."""

    def test_archive_status_force_carries_archived_task_ids(
        self, conn: sqlite3.Connection
    ) -> None:
        ws, st = _ws_status(conn)
        t1 = _task(conn, ws.id, st.id, "t1")
        t2 = _task(conn, ws.id, st.id, "t2")
        calls: list[tuple] = []

        def fake_fire(event, **kwargs):
            calls.append((event, kwargs))

        with patch("stx.service.fire_hooks", side_effect=fake_fire):
            service.archive_status(conn, st.id, force=True, source="test")

        status_calls = [(e, k) for e, k in calls if e == HookEvent.STATUS_ARCHIVED]
        assert len(status_calls) == 1
        for _, kwargs in status_calls:
            assert sorted(kwargs["archived_task_ids"]) == sorted([t1.id, t2.id])
        task_archived = [e for e, _ in calls if e == HookEvent.TASK_ARCHIVED]
        assert task_archived == []

    def test_archive_status_reassign_carries_reassigned_task_ids(
        self, conn: sqlite3.Connection
    ) -> None:
        ws = service.create_workspace(conn, "ws2")
        src = service.create_status(conn, ws.id, "src")
        dst = service.create_status(conn, ws.id, "dst")
        t1 = _task(conn, ws.id, src.id, "t1")
        t2 = _task(conn, ws.id, src.id, "t2")
        calls: list[tuple] = []

        def fake_fire(event, **kwargs):
            calls.append((event, kwargs))

        with patch("stx.service.fire_hooks", side_effect=fake_fire):
            service.archive_status(conn, src.id, reassign_to_status_id=dst.id, source="test")

        status_calls = [(e, k) for e, k in calls if e == HookEvent.STATUS_ARCHIVED]
        assert len(status_calls) == 1
        for _, kwargs in status_calls:
            assert sorted(kwargs["reassigned_task_ids"]) == sorted([t1.id, t2.id])
            assert kwargs["reassigned_to"] == dst.id
        task_moved = [e for e, _ in calls if e == HookEvent.TASK_MOVED]
        assert task_moved == []

    def test_cascade_archive_group_carries_id_arrays(
        self, conn: sqlite3.Connection
    ) -> None:
        ws, st = _ws_status(conn)
        parent = service.create_group(conn, ws.id, "parent")
        child = service.create_group(conn, ws.id, "child", parent_id=parent.id)
        t1 = _task(conn, ws.id, st.id, "t1")
        t2 = _task(conn, ws.id, st.id, "t2")
        service.assign_task_to_group(conn, t1.id, parent.id, source="test")
        service.assign_task_to_group(conn, t2.id, child.id, source="test")
        calls: list[tuple] = []

        def fake_fire(event, **kwargs):
            calls.append((event, kwargs))

        with patch("stx.service.fire_hooks", side_effect=fake_fire):
            service.cascade_archive_group(conn, parent.id, source="test")

        group_calls = [(e, k) for e, k in calls if e == HookEvent.GROUP_ARCHIVED]
        assert len(group_calls) == 1
        for _, kwargs in group_calls:
            assert sorted(kwargs["archived_task_ids"]) == sorted([t1.id, t2.id])
            assert kwargs["archived_group_ids"] == [child.id]
        task_archived = [e for e, _ in calls if e == HookEvent.TASK_ARCHIVED]
        assert task_archived == []

    def test_cascade_archive_workspace_carries_id_arrays(
        self, conn: sqlite3.Connection
    ) -> None:
        ws = service.create_workspace(conn, "ws_cascade")
        st = service.create_status(conn, ws.id, "todo")
        grp = service.create_group(conn, ws.id, "grp")
        t1 = _task(conn, ws.id, st.id, "t1")
        calls: list[tuple] = []

        def fake_fire(event, **kwargs):
            calls.append((event, kwargs))

        with patch("stx.service.fire_hooks", side_effect=fake_fire):
            service.cascade_archive_workspace(conn, ws.id, source="test")

        ws_calls = [(e, k) for e, k in calls if e == HookEvent.WORKSPACE_ARCHIVED]
        assert len(ws_calls) == 1
        for _, kwargs in ws_calls:
            assert kwargs["archived_task_ids"] == [t1.id]
            assert kwargs["archived_group_ids"] == [grp.id]
            assert kwargs["archived_status_ids"] == [st.id]
        task_archived = [e for e, _ in calls if e == HookEvent.TASK_ARCHIVED]
        assert task_archived == []

    def test_archive_status_no_tasks_has_no_extras(
        self, conn: sqlite3.Connection
    ) -> None:
        ws, st = _ws_status(conn)
        calls: list[tuple] = []

        def fake_fire(event, **kwargs):
            calls.append((event, kwargs))

        with patch("stx.service.fire_hooks", side_effect=fake_fire):
            service.archive_status(conn, st.id, force=True, source="test")

        for _, kwargs in calls:
            assert "archived_task_ids" not in kwargs
            assert "reassigned_task_ids" not in kwargs
