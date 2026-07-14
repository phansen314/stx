"""cli/__main__.py — command logic, exercised with fake clients (no daemon)."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from cli import __main__ as m
from cli.context import CliError
from stxc import StxApiError
from stxc.models import Status, Transition, Workspace


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
    behavior = "ok"  # "ok" | "down" | "apierror"

    def __init__(self, base_url) -> None:
        self.base_url = base_url

    def ping(self) -> bool:
        return _MainClient.behavior != "down"

    def list_workspaces(self):
        if _MainClient.behavior == "apierror":
            raise StxApiError(500, {"error": "Boom"})
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
