"""Integration tests for hook wiring in service.py task mutations (task 158)."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

from stx import service
from stx.hooks import HookEvent, HookTiming
from stx.service import _determine_task_events
from stx.models import HookRejectionError


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
    def test_pre_hook_fires_with_proposed(self, conn: sqlite3.Connection) -> None:
        ws, st = _ws_status(conn)
        calls = []

        def fake_fire(event, timing, **kwargs):
            calls.append((event, timing, kwargs))

        with patch("stx.service.fire_hooks", side_effect=fake_fire):
            service.create_task(conn, ws.id, "mytask", st.id)

        pre = [(e, t, k) for e, t, k in calls if t == HookTiming.PRE]
        assert len(pre) == 1
        event, timing, kwargs = pre[0]
        assert event == HookEvent.TASK_CREATED
        assert kwargs["proposed"]["title"] == "mytask"
        assert kwargs["entity"] is None

    def test_post_hook_fires_with_entity(self, conn: sqlite3.Connection) -> None:
        ws, st = _ws_status(conn)
        post_calls = []

        def fake_fire(event, timing, **kwargs):
            if timing == HookTiming.POST:
                post_calls.append(kwargs)

        with patch("stx.service.fire_hooks", side_effect=fake_fire):
            task = service.create_task(conn, ws.id, "mytask", st.id)

        assert len(post_calls) == 1
        entity = post_calls[0]["entity"]
        assert entity is not None
        assert entity.id == task.id
        assert entity.title == "mytask"

    def test_pre_hook_rejection_blocks_create(
        self, conn: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        hooks_toml = tmp_path / "hooks.toml"
        hooks_toml.write_text(
            '[[hooks]]\nevent = "task.created"\ntiming = "pre"\ncommand = "exit 1"\n'
        )
        monkeypatch.setattr("stx.hooks.DEFAULT_HOOKS_PATH", hooks_toml)
        ws, st = _ws_status(conn)
        with pytest.raises(HookRejectionError):
            service.create_task(conn, ws.id, "blocked", st.id)
        # task must not exist
        assert service.list_tasks(conn, ws.id) == ()


# ---------------------------------------------------------------------------
# update_task hooks — event selection
# ---------------------------------------------------------------------------

class TestUpdateTaskHooks:
    def test_status_change_fires_moved(self, conn: sqlite3.Connection) -> None:
        ws, st = _ws_status(conn)
        st2 = service.create_status(conn, ws.id, "done")
        task = _task(conn, ws.id, st.id)
        fired = []
        with patch("stx.service.fire_hooks", side_effect=lambda e, t, **kw: fired.append((e, t))):
            service.update_task(conn, task.id, {"status_id": st2.id}, "test")
        events = [e for e, _ in fired]
        assert HookEvent.TASK_MOVED in events

    def test_done_true_fires_task_done(self, conn: sqlite3.Connection) -> None:
        ws, st = _ws_status(conn)
        task = _task(conn, ws.id, st.id)
        fired = []
        with patch("stx.service.fire_hooks", side_effect=lambda e, t, **kw: fired.append((e, t))):
            service.update_task(conn, task.id, {"done": True}, "test")
        events = [e for e, _ in fired]
        assert HookEvent.TASK_DONE in events

    def test_done_false_fires_task_undone(self, conn: sqlite3.Connection) -> None:
        ws, st = _ws_status(conn)
        task = _task(conn, ws.id, st.id)
        service.update_task(conn, task.id, {"done": True}, "test")
        fired = []
        with patch("stx.service.fire_hooks", side_effect=lambda e, t, **kw: fired.append((e, t))):
            service.update_task(conn, task.id, {"done": False}, "test")
        events = [e for e, _ in fired]
        assert HookEvent.TASK_UNDONE in events

    def test_title_change_fires_updated(self, conn: sqlite3.Connection) -> None:
        ws, st = _ws_status(conn)
        task = _task(conn, ws.id, st.id)
        fired = []
        with patch("stx.service.fire_hooks", side_effect=lambda e, t, **kw: fired.append((e, t))):
            service.update_task(conn, task.id, {"title": "new title"}, "test")
        events = [e for e, _ in fired]
        assert HookEvent.TASK_UPDATED in events

    def test_terminal_status_fires_moved_and_done_post(
        self, conn: sqlite3.Connection
    ) -> None:
        ws, st = _ws_status(conn)
        terminal_st = service.create_status(conn, ws.id, "done")
        service.update_status(conn, terminal_st.id, {"is_terminal": True})
        task = _task(conn, ws.id, st.id)
        fired_post = []
        def fake_fire(event, timing, **kw):
            if timing == HookTiming.POST:
                fired_post.append(event)
        with patch("stx.service.fire_hooks", side_effect=fake_fire):
            service.update_task(conn, task.id, {"status_id": terminal_st.id}, "test")
        assert HookEvent.TASK_MOVED in fired_post
        assert HookEvent.TASK_DONE in fired_post

    def test_pre_hook_rejection_blocks_update(
        self, conn: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        hooks_toml = tmp_path / "hooks.toml"
        hooks_toml.write_text(
            '[[hooks]]\nevent = "task.updated"\ntiming = "pre"\ncommand = "exit 1"\n'
        )
        monkeypatch.setattr("stx.hooks.DEFAULT_HOOKS_PATH", hooks_toml)
        ws, st = _ws_status(conn)
        task = _task(conn, ws.id, st.id)
        with pytest.raises(HookRejectionError):
            service.update_task(conn, task.id, {"title": "blocked"}, "test")
        assert service.get_task(conn, task.id).title == "task A"


# ---------------------------------------------------------------------------
# archive_task hooks
# ---------------------------------------------------------------------------

class TestArchiveTaskHooks:
    def test_pre_and_post_fire(self, conn: sqlite3.Connection) -> None:
        ws, st = _ws_status(conn)
        task = _task(conn, ws.id, st.id)
        fired = []
        with patch("stx.service.fire_hooks", side_effect=lambda e, t, **kw: fired.append((e, t))):
            service.archive_task(conn, task.id, source="test")
        events_by_timing: dict = {}
        for e, t in fired:
            events_by_timing.setdefault(t, []).append(e)
        assert HookEvent.TASK_ARCHIVED in events_by_timing.get(HookTiming.PRE, [])
        assert HookEvent.TASK_ARCHIVED in events_by_timing.get(HookTiming.POST, [])

    def test_pre_rejection_blocks_archive(
        self, conn: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        hooks_toml = tmp_path / "hooks.toml"
        hooks_toml.write_text(
            '[[hooks]]\nevent = "task.archived"\ntiming = "pre"\ncommand = "exit 1"\n'
        )
        monkeypatch.setattr("stx.hooks.DEFAULT_HOOKS_PATH", hooks_toml)
        ws, st = _ws_status(conn)
        task = _task(conn, ws.id, st.id)
        with pytest.raises(HookRejectionError):
            service.archive_task(conn, task.id, source="test")
        assert not service.get_task(conn, task.id).archived


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
        def fake_fire(event, timing, **kw):
            if event == HookEvent.TASK_TRANSFERRED and timing == HookTiming.POST:
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
    def test_set_meta_fires_pre_and_post(self, conn: sqlite3.Connection) -> None:
        ws, st = _ws_status(conn)
        task = _task(conn, ws.id, st.id)
        fired = []
        with patch("stx.service.fire_hooks", side_effect=lambda e, t, **kw: fired.append((e, t, kw))):
            service.set_task_meta(conn, task.id, "tag", "urgent")
        pre = [(e, t, k) for e, t, k in fired if t == HookTiming.PRE]
        post = [(e, t, k) for e, t, k in fired if t == HookTiming.POST]
        assert len(pre) == 1 and pre[0][0] == HookEvent.TASK_META_SET
        assert pre[0][2]["meta_key"] == "tag"
        assert pre[0][2]["meta_value"] == "urgent"
        assert len(post) == 1 and post[0][0] == HookEvent.TASK_META_SET

    def test_set_meta_no_hook_when_unchanged(self, conn: sqlite3.Connection) -> None:
        ws, st = _ws_status(conn)
        task = _task(conn, ws.id, st.id)
        service.set_task_meta(conn, task.id, "tag", "v")
        fired = []
        with patch("stx.service.fire_hooks", side_effect=lambda e, t, **kw: fired.append(e)):
            service.set_task_meta(conn, task.id, "tag", "v")  # same value
        assert fired == []

    def test_remove_meta_fires(self, conn: sqlite3.Connection) -> None:
        ws, st = _ws_status(conn)
        task = _task(conn, ws.id, st.id)
        service.set_task_meta(conn, task.id, "x", "1")
        fired = []
        with patch("stx.service.fire_hooks", side_effect=lambda e, t, **kw: fired.append(e)):
            service.remove_task_meta(conn, task.id, "x")
        assert HookEvent.TASK_META_REMOVED in fired

    def test_replace_metadata_fires_per_key(self, conn: sqlite3.Connection) -> None:
        ws, st = _ws_status(conn)
        task = _task(conn, ws.id, st.id)
        service.set_task_meta(conn, task.id, "a", "old")
        service.set_task_meta(conn, task.id, "b", "keep")
        fired = []
        with patch("stx.service.fire_hooks", side_effect=lambda e, t, **kw: fired.append((e, kw["meta_key"]))):
            service.replace_task_metadata(conn, task.id, {"a": "new", "c": "added"}, source="test")
        # key "a" changed, key "c" added (META_SET), key "b" removed (META_REMOVED)
        event_keys = [(e, k) for e, k in fired]
        assert (HookEvent.TASK_META_SET, "a") in event_keys
        assert (HookEvent.TASK_META_SET, "c") in event_keys
        assert (HookEvent.TASK_META_REMOVED, "b") in event_keys


# ---------------------------------------------------------------------------
# CLI exit code 7
# ---------------------------------------------------------------------------

class TestCliExitCode:
    def test_exit_7_on_pre_hook_rejection(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from stx.cli import main, EXIT_HOOK_REJECTED
        from stx.connection import get_connection, init_db

        hooks_toml = tmp_path / "hooks.toml"
        hooks_toml.write_text(
            '[[hooks]]\nevent = "task.created"\ntiming = "pre"\ncommand = "exit 1"\n'
        )
        monkeypatch.setattr("stx.hooks.DEFAULT_HOOKS_PATH", hooks_toml)

        db = tmp_path / "test.db"
        cli_conn = get_connection(db)
        init_db(cli_conn)
        ws = service.create_workspace(cli_conn, "cli-test")
        service.create_status(cli_conn, ws.id, "todo")
        # Persist active workspace so the CLI can resolve it
        from stx.active_workspace import set_active_workspace_id
        set_active_workspace_id(tmp_path / "tui.toml", ws.id)
        cli_conn.close()

        monkeypatch.setattr("stx.cli.DEFAULT_DB_PATH", db)

        with pytest.raises(SystemExit) as exc_info:
            main(["task", "create", "blocked-task", "--status", "todo"])
        assert exc_info.value.code == EXIT_HOOK_REJECTED


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
        with patch("stx.service.fire_hooks", side_effect=lambda e, t, **kw: (
            fired_post.append(e) if t == HookTiming.POST else None
        )):
            service.create_task(conn, ws.id, "done-on-arrival", st.id)
        assert HookEvent.TASK_CREATED in fired_post
        assert HookEvent.TASK_DONE in fired_post

    def test_non_terminal_status_create_no_task_done(
        self, conn: sqlite3.Connection
    ) -> None:
        ws, st = _ws_status(conn)
        fired_post = []
        with patch("stx.service.fire_hooks", side_effect=lambda e, t, **kw: (
            fired_post.append(e) if t == HookTiming.POST else None
        )):
            service.create_task(conn, ws.id, "normal", st.id)
        assert HookEvent.TASK_CREATED in fired_post
        assert HookEvent.TASK_DONE not in fired_post


class TestUpdateTaskNoOpShortCircuit:
    """H3 fix: update_task with no real delta skips hooks and DB write."""

    def test_no_change_fires_no_hooks(self, conn: sqlite3.Connection) -> None:
        ws, st = _ws_status(conn)
        task = _task(conn, ws.id, st.id)
        fired = []
        with patch("stx.service.fire_hooks", side_effect=lambda e, t, **kw: fired.append(e)):
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
        with patch("stx.service.fire_hooks", side_effect=lambda e, t, **kw: fired_keys.append(kw["meta_key"])):
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
        with patch("stx.service.fire_hooks", side_effect=lambda e, t, **kw: fired.append(e)):
            service.move_task(conn, task.id, st2.id, "test")
        assert HookEvent.TASK_MOVED in fired

    def test_mark_task_done_fires_done(self, conn: sqlite3.Connection) -> None:
        ws, st = _ws_status(conn)
        task = _task(conn, ws.id, st.id)
        fired = []
        with patch("stx.service.fire_hooks", side_effect=lambda e, t, **kw: fired.append(e)):
            service.mark_task_done(conn, task.id, source="test")
        assert HookEvent.TASK_DONE in fired

    def test_mark_task_undone_fires_undone(self, conn: sqlite3.Connection) -> None:
        ws, st = _ws_status(conn)
        task = _task(conn, ws.id, st.id)
        service.mark_task_done(conn, task.id, source="test")
        fired = []
        with patch("stx.service.fire_hooks", side_effect=lambda e, t, **kw: fired.append(e)):
            service.mark_task_undone(conn, task.id, source="test")
        assert HookEvent.TASK_UNDONE in fired

    def test_assign_task_to_group_fires_assigned(self, conn: sqlite3.Connection) -> None:
        ws, st = _ws_status(conn)
        task = _task(conn, ws.id, st.id)
        grp = service.create_group(conn, ws.id, "grp")
        fired = []
        with patch("stx.service.fire_hooks", side_effect=lambda e, t, **kw: fired.append(e)):
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
        with patch("stx.service.fire_hooks", side_effect=lambda e, t, **kw: fired.append(e)):
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
        with patch("stx.service.fire_hooks", side_effect=lambda e, t, **kw: fired.append(e)):
            service.mark_task_done(conn, task.id, source="test")
        assert fired == []

    def test_mark_undone_not_done_fires_no_hooks(
        self, conn: sqlite3.Connection
    ) -> None:
        ws, st = _ws_status(conn)
        task = _task(conn, ws.id, st.id)
        fired = []
        with patch("stx.service.fire_hooks", side_effect=lambda e, t, **kw: fired.append(e)):
            service.mark_task_undone(conn, task.id, source="test")
        assert fired == []

    def test_remove_meta_absent_key_fires_no_hooks(
        self, conn: sqlite3.Connection
    ) -> None:
        ws, st = _ws_status(conn)
        task = _task(conn, ws.id, st.id)
        fired = []
        with patch("stx.service.fire_hooks", side_effect=lambda e, t, **kw: fired.append(e)):
            with pytest.raises(LookupError):
                service.remove_task_meta(conn, task.id, "nonexistent")
        assert fired == []
