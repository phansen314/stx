"""cli/__main__.py — command logic, exercised with fake clients (no daemon)."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from cli import __main__ as m
from cli.context import CliError
from stxc import StxApiError, StxConnError
from stxc.models import Status, Task, Track, Transition, Workspace


def conflict() -> StxApiError:
    return StxApiError(409, {"error": "VersionConflict", "message": "stale"})


def illegal() -> StxApiError:
    return StxApiError(422, {"error": "IllegalTransition", "message": "no"})


def _fn(behaviors: list):
    """A fake `fn(version)` that pops a behavior per call: an Exception is raised, else returned."""
    calls: list[int] = []

    def fn(v: int):
        calls.append(v)
        b = behaviors.pop(0)
        if isinstance(b, Exception):
            raise b
        return b

    fn.calls = calls  # type: ignore[attr-defined]
    return fn


class _RetryClient:
    def __init__(self, versions: list[int]) -> None:
        self._versions = list(versions)
        self.detail_calls = 0

    def task_detail(self, task_id: int) -> dict:
        self.detail_calls += 1
        return {"task": {"version": self._versions.pop(0)}}


class TestRetryConflict:
    def test_success_first_try(self) -> None:
        c = _RetryClient([7])
        fn = _fn(["ok"])
        assert m._retry_conflict(c, 1, fn) == "ok"
        assert fn.calls == [7]
        assert c.detail_calls == 1

    def test_one_conflict_then_success(self) -> None:
        c = _RetryClient([7, 8])  # re-read returns a fresh version
        fn = _fn([conflict(), "ok"])
        assert m._retry_conflict(c, 1, fn) == "ok"
        assert fn.calls == [7, 8]  # retried with the re-read version
        assert c.detail_calls == 2

    def test_second_conflict_propagates(self) -> None:
        c = _RetryClient([7, 8])
        fn = _fn([conflict(), conflict()])
        with pytest.raises(StxApiError) as ei:
            m._retry_conflict(c, 1, fn)
        assert ei.value.variant == "VersionConflict"

    def test_non_conflict_reraised_immediately(self) -> None:
        c = _RetryClient([7])
        fn = _fn([illegal()])
        with pytest.raises(StxApiError) as ei:
            m._retry_conflict(c, 1, fn)
        assert ei.value.variant == "IllegalTransition"
        assert c.detail_calls == 1  # no re-read on a non-conflict error


class _MvClient:
    def __init__(self, statuses, transitions, move_result) -> None:
        self._statuses = statuses
        self._transitions = transitions
        self._move_result = move_result
        self._detail = {"task": {"workspaceId": 1, "statusId": 10, "version": 0}}

    def task_detail(self, task_id): return self._detail
    def statuses(self, ws): return self._statuses
    def transitions(self, ws): return self._transitions

    def move_status(self, task_id, to, version):
        if isinstance(self._move_result, Exception):
            raise self._move_result
        return self._move_result


class TestCmdMvDone:
    def _statuses(self):
        return [Status(id=10, name="todo"), Status(id=30, name="doing"),
                Status(id=20, name="done", terminal=True)]

    def test_mv_illegal_transition_message(self) -> None:
        c = _MvClient(self._statuses(), [Transition(from_status_id=10, to_status_id=30)], illegal())
        args = SimpleNamespace(id=1, status="done", json=False)
        with pytest.raises(CliError, match=r"illegal transition to 'done'. legal from 'todo': doing"):
            m.cmd_mv(c, args)

    def test_done_picks_terminal_then_illegal_message(self) -> None:
        c = _MvClient(self._statuses(), [Transition(from_status_id=10, to_status_id=30)], illegal())
        args = SimpleNamespace(id=1, json=False)
        with pytest.raises(CliError, match=r"can't reach terminal 'done' directly. legal from 'todo': doing"):
            m.cmd_done(c, args)

    def test_done_no_terminal_status(self) -> None:
        c = _MvClient([Status(id=10, name="todo")], [], None)
        args = SimpleNamespace(id=1, json=False)
        with pytest.raises(CliError, match="no terminal status"):
            m.cmd_done(c, args)


class _WsClient:
    def list_workspaces(self): return [Workspace(id=1, name="ws")]


class TestCmdAddGuard:
    def test_both_track_and_segment_rejected(self) -> None:
        args = SimpleNamespace(workspace="ws", track="t", segment=5)
        with pytest.raises(CliError, match="exactly one of"):
            m.cmd_add(_WsClient(), args)

    def test_neither_track_nor_segment_rejected(self) -> None:
        args = SimpleNamespace(workspace="ws", track=None, segment=None)
        with pytest.raises(CliError, match="exactly one of"):
            m.cmd_add(_WsClient(), args)


class _EditClient:
    def __init__(self) -> None:
        self.edit_kwargs = None

    def task_detail(self, task_id): return {"task": {"version": 2, "workspaceId": 1}}

    def edit_task(self, task_id, version, **changes):
        self.edit_kwargs = changes
        return SimpleNamespace(id=task_id, title=changes.get("title", "t"))


def _edit_args(**over):
    base = dict(id=1, title=None, desc=None, priority=None, kind=None,
               clear_kind=False, json=False)
    base.update(over)
    return SimpleNamespace(**base)


class TestCmdEdit:
    def test_nothing_to_edit(self) -> None:
        with pytest.raises(CliError, match="nothing to edit"):
            m.cmd_edit(_EditClient(), _edit_args())

    def test_builds_changes_dict(self, capsys) -> None:
        c = _EditClient()
        m.cmd_edit(c, _edit_args(title="new", clear_kind=True))
        assert c.edit_kwargs == {"title": "new", "clearKind": True}

    def test_builds_priority_change(self, capsys) -> None:
        c = _EditClient()
        m.cmd_edit(c, _edit_args(priority=5))
        assert c.edit_kwargs == {"priority": 5}


class _ArchiveClient:
    def __init__(self) -> None:
        self.archived = None

    def archive(self, kind, entity_id): self.archived = (kind, entity_id)


class TestCmdArchive:
    def test_track_without_yes_rejected(self) -> None:
        args = SimpleNamespace(type="track", id=3, yes=False, json=False)
        with pytest.raises(CliError, match="pass --yes"):
            m.cmd_archive(_ArchiveClient(), args)

    def test_task_archives_via_path_map(self, capsys) -> None:
        c = _ArchiveClient()
        m.cmd_archive(c, SimpleNamespace(type="task", id=3, yes=False, json=False))
        assert c.archived == ("tasks", 3)


class _MetaClient:
    """Fake client whose metadata blob round-trips through edit_*; records each edit's changes."""

    def __init__(self, blob: str = "{}") -> None:
        self.task_blob = self.ws_blob = self.tr_blob = blob
        self.task_ver = self.ws_ver = self.tr_ver = 0
        self.edits: list = []

    def task_detail(self, tid):
        return {"task": {"metadataJson": self.task_blob, "version": self.task_ver}}

    def list_workspaces(self):
        return [Workspace(id=1, name="ws", metadata_json=self.ws_blob, version=self.ws_ver)]

    def tracks(self, ws_id):
        return [Track(id=5, workspace_id=1, name="t", metadata_json=self.tr_blob, version=self.tr_ver)]

    def edit_task(self, tid, v, **ch):
        self.edits.append(("task", ch)); self.task_blob = ch["metadata_json"]; self.task_ver += 1
        return Task(id=tid, metadata_json=self.task_blob)

    def edit_workspace(self, ws, v, **ch):
        self.edits.append(("ws", ch)); self.ws_blob = ch["metadata_json"]; self.ws_ver += 1
        return Workspace(id=ws, metadata_json=self.ws_blob)

    def edit_track(self, tr, v, **ch):
        self.edits.append(("track", ch)); self.tr_blob = ch["metadata_json"]; self.tr_ver += 1
        return Track(id=tr, metadata_json=self.tr_blob)


def _meta_args(sub, **over):
    base = dict(sub=sub, task=None, workspace=None, track=None,
                key=None, value=None, string=False, json=False)
    base.update(over)
    return SimpleNamespace(**base)


class TestCmdMeta:
    def test_set_then_ls_task(self, capsys) -> None:
        c = _MetaClient()
        m.cmd_meta(c, _meta_args("set", task=1, key="dueDate", value="2026-08-01"))
        assert c.edits[-1] == ("task", {"metadata_json": '{"dueDate": "2026-08-01"}'})
        m.cmd_meta(c, _meta_args("ls", task=1))
        assert 'dueDate = "2026-08-01"' in capsys.readouterr().out

    def test_json_value_parsed(self) -> None:
        c = _MetaClient()
        m.cmd_meta(c, _meta_args("set", task=1, key="n", value="5"))
        assert '"n": 5' in c.task_blob  # int, not the string "5"

    def test_string_flag_forces_literal(self) -> None:
        c = _MetaClient()
        m.cmd_meta(c, _meta_args("set", task=1, key="n", value="5", string=True))
        assert '"n": "5"' in c.task_blob

    def test_get_missing_key_errors(self) -> None:
        with pytest.raises(CliError, match="no metadata key 'nope'"):
            m.cmd_meta(_MetaClient(), _meta_args("get", task=1, key="nope"))

    def test_del_missing_key_errors(self) -> None:
        with pytest.raises(CliError, match="no metadata key 'nope'"):
            m.cmd_meta(_MetaClient(), _meta_args("del", task=1, key="nope"))

    def test_del_removes_key(self) -> None:
        c = _MetaClient('{"a": 1, "b": 2}')
        m.cmd_meta(c, _meta_args("del", task=1, key="a"))
        assert c.task_blob == '{"b": 2}'

    def test_workspace_target(self) -> None:
        c = _MetaClient()
        m.cmd_meta(c, _meta_args("set", workspace="ws", key="theme", value="dark"))
        assert c.edits[-1][0] == "ws" and '"theme": "dark"' in c.ws_blob

    def test_track_target(self) -> None:
        c = _MetaClient()
        m.cmd_meta(c, _meta_args("set", workspace="ws", track="t", key="owner", value="paul"))
        assert c.edits[-1][0] == "track" and '"owner": "paul"' in c.tr_blob

    def test_non_object_blob_errors(self) -> None:
        with pytest.raises(CliError, match="not a JSON object"):
            m.cmd_meta(_MetaClient("[1, 2]"), _meta_args("ls", task=1))

    def test_no_target_rejected(self) -> None:
        with pytest.raises(CliError, match="exactly one target"):
            m.cmd_meta(None, _meta_args("ls"))

    def test_both_targets_rejected(self) -> None:
        with pytest.raises(CliError, match="exactly one target"):
            m.cmd_meta(None, _meta_args("ls", task=1, workspace="ws"))

    def test_track_without_workspace_rejected(self) -> None:
        with pytest.raises(CliError, match="--track requires -w"):
            m.cmd_meta(None, _meta_args("ls", task=1, track="t"))


class _MetaConflictClient:
    """edit_task raises VersionConflict once, then succeeds — exercises the RMW retry."""

    def __init__(self) -> None:
        self.blob = "{}"
        self.ver = 0
        self.edit_calls = 0

    def task_detail(self, tid):
        return {"task": {"metadataJson": self.blob, "version": self.ver}}

    def edit_task(self, tid, v, **ch):
        self.edit_calls += 1
        if self.edit_calls == 1:
            raise StxApiError(409, {"error": "VersionConflict", "message": "stale"})
        self.blob = ch["metadata_json"]; self.ver += 1
        return Task(id=tid, metadata_json=self.blob)


class TestCmdMetaRetry:
    def test_set_retries_on_conflict(self) -> None:
        c = _MetaConflictClient()
        m.cmd_meta(c, _meta_args("set", task=1, key="k", value="v"))
        assert c.edit_calls == 2 and '"k": "v"' in c.blob


class _GraphClient:
    def __init__(self, edges) -> None:
        self._edges = edges

    def list_workspaces(self): return [Workspace(id=1, name="ws")]
    def statuses(self, ws): return [Status(id=10, name="todo"),
                                    Status(id=20, name="done", terminal=True)]
    def tracks(self, ws): return [Track(id=5, name="main"), Track(id=6, name="other")]

    def track_tasks(self, tr):
        if tr == 5:
            return [Task(id=1, title="a", status_id=10), Task(id=2, title="b", status_id=20)]
        return [Task(id=3, title="c", status_id=10)]

    def edges(self, ws): return self._edges


def _graph_args(**over):
    base = dict(workspace="ws", track=None, blocks_only=False, json=False)
    base.update(over)
    return SimpleNamespace(**base)


_GRAPH_EDGES = {"blocks": [{"sourceTaskId": 1, "targetTaskId": 2}],
                "relates": [{"kind": "spawns", "sourceTaskId": 1, "targetTaskId": 3}]}


class TestCmdGraph:
    def test_dot_includes_blocks_and_relates(self, capsys) -> None:
        m.cmd_graph(_GraphClient(_GRAPH_EDGES), _graph_args())
        out = capsys.readouterr().out
        assert '"1" -> "2";' in out
        assert '"1" -> "3" [style=dashed, label="spawns"];' in out
        assert 'fillcolor="#cde7cd"' in out  # task 2 is terminal (done)

    def test_blocks_only_drops_relates(self, capsys) -> None:
        m.cmd_graph(_GraphClient(_GRAPH_EDGES), _graph_args(blocks_only=True))
        out = capsys.readouterr().out
        assert '"1" -> "2";' in out and "spawns" not in out

    def test_track_scope_drops_out_of_scope_edge(self, capsys) -> None:
        # scope to track 'main' (tasks 1,2); relate 1->3 (task 3 in 'other') is dropped
        m.cmd_graph(_GraphClient(_GRAPH_EDGES), _graph_args(track="main"))
        out = capsys.readouterr().out
        assert '"1" -> "2";' in out and "spawns" not in out

    def test_json_payload_shape(self, capsys) -> None:
        import json as _json
        m.cmd_graph(_GraphClient(_GRAPH_EDGES), _graph_args(json=True))
        payload = _json.loads(capsys.readouterr().out)
        assert payload["workspace"] == "ws"
        assert payload["blocks"] == [[1, 2]]
        assert payload["relates"] == [[1, 3, "spawns"]]
        assert {n["id"] for n in payload["nodes"]} == {1, 2, 3}


class TestBuildParser:
    def test_ls(self) -> None:
        ns = m.build_parser().parse_args(["ls"])
        assert ns.cmd == "ls" and ns.fn is m.cmd_ls

    def test_mv_positionals(self) -> None:
        ns = m.build_parser().parse_args(["mv", "5", "done"])
        assert ns.id == 5 and ns.status == "done"

    def test_archive_choices(self) -> None:
        ns = m.build_parser().parse_args(["archive", "task", "3"])
        assert ns.type == "task" and ns.id == 3 and ns.yes is False

    def test_meta_set_positionals(self) -> None:
        ns = m.build_parser().parse_args(["meta", "set", "--task", "5", "k", "v"])
        assert ns.cmd == "meta" and ns.sub == "set" and ns.task == 5
        assert ns.key == "k" and ns.value == "v" and ns.fn is m.cmd_meta

    def test_meta_ls_workspace(self) -> None:
        ns = m.build_parser().parse_args(["meta", "ls", "-w", "auth"])
        assert ns.sub == "ls" and ns.workspace == "auth" and ns.fn is m.cmd_meta

    def test_graph_flags(self) -> None:
        ns = m.build_parser().parse_args(["graph", "-w", "auth", "-t", "main", "--blocks-only"])
        assert ns.cmd == "graph" and ns.workspace == "auth" and ns.track == "main"
        assert ns.blocks_only is True and ns.fn is m.cmd_graph

    def test_transition_defaults_sub_new_and_from_attr(self) -> None:
        ns = m.build_parser().parse_args(["transition", "-w", "ws", "--from", "a", "--to", "b"])
        assert ns.sub == "new"
        assert getattr(ns, "from") == "a" and ns.to == "b"

    def test_missing_subcommand_exits(self) -> None:
        with pytest.raises(SystemExit):
            m.build_parser().parse_args([])

    def test_bad_archive_choice_exits(self) -> None:
        with pytest.raises(SystemExit):
            m.build_parser().parse_args(["archive", "bogus", "1"])

    def test_archive_path_map(self) -> None:
        assert m._ARCHIVE_PATH == {"task": "tasks", "segment": "segments",
                                   "track": "tracks", "workspace": "workspaces"}

    def test_json_flag_after_subcommand(self) -> None:
        assert m.parse_cli(["ls", "--json"]).json is True

    def test_json_flag_before_subcommand(self) -> None:
        # regression: --json before the subcommand must NOT be clobbered back to False
        assert m.parse_cli(["--json", "ls"]).json is True

    def test_json_flag_absent_defaults_false(self) -> None:
        assert m.parse_cli(["ls"]).json is False

    def test_base_url_either_position(self) -> None:
        assert m.parse_cli(["--base-url", "http://x", "ls"]).base_url == "http://x"
        assert m.parse_cli(["ls", "--base-url", "http://y"]).base_url == "http://y"

    def test_base_url_absent_defaults(self) -> None:
        assert m.parse_cli(["ls"]).base_url == m.DEFAULT_URL

    def test_parse_cli_still_dispatches_subcommand(self) -> None:
        # globals stripped, subcommand + its args still parse and resolve fn
        ns = m.parse_cli(["--json", "mv", "5", "done"])
        assert ns.cmd == "mv" and ns.id == 5 and ns.status == "done" and ns.fn is m.cmd_mv

    def test_parse_cli_missing_subcommand_exits(self) -> None:
        with pytest.raises(SystemExit):
            m.parse_cli(["--json"])


class _MainClient:
    """Patched in for cli.__main__.Client so main() never touches a socket."""
    behavior = "ok"  # "ok" | "down" | "apierror" | "connerror"

    def __init__(self, base_url) -> None:
        self.base_url = base_url

    def ping(self) -> bool:
        return _MainClient.behavior != "down"

    def list_workspaces(self):
        if _MainClient.behavior == "apierror":
            raise StxApiError(500, {"error": "Boom"})
        # Daemon dies AFTER ping succeeds: the client wraps the transport failure in StxConnError.
        if _MainClient.behavior == "connerror":
            raise StxConnError(ConnectionError("connection reset"))
        return []

    def tracks(self, ws_id):
        return []


class TestMainExitCodes:
    def test_ok_returns_zero(self, monkeypatch, capsys) -> None:
        _MainClient.behavior = "ok"
        monkeypatch.setattr(m, "Client", _MainClient)
        assert m.main(["ls"]) == 0
        assert "(no workspaces)" in capsys.readouterr().out

    def test_daemon_unreachable_returns_one(self, monkeypatch, capsys) -> None:
        _MainClient.behavior = "down"
        monkeypatch.setattr(m, "Client", _MainClient)
        assert m.main(["ls"]) == 1
        assert "daemon unreachable" in capsys.readouterr().err

    def test_api_error_returns_one(self, monkeypatch, capsys) -> None:
        _MainClient.behavior = "apierror"
        monkeypatch.setattr(m, "Client", _MainClient)
        assert m.main(["ls"]) == 1
        assert "Boom" in capsys.readouterr().err

    def test_mid_command_conn_error_returns_one_no_traceback(self, monkeypatch, capsys) -> None:
        # StxConnError subclasses StxError, NOT requests.RequestException — main() must catch the
        # base and print a clean message instead of letting it escape as a traceback.
        _MainClient.behavior = "connerror"
        monkeypatch.setattr(m, "Client", _MainClient)
        assert m.main(["ls"]) == 1
        assert "daemon request failed" in capsys.readouterr().err
