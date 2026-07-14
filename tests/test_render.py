"""cli/render.py — pure text/JSON renderers. Built with the real stxc dataclasses + plain dicts."""
from __future__ import annotations

import json

import pytest

from cli import render
from stxc.models import Segment, Status, Task, Track, Workspace


class TestDumps:
    def test_dataclass_to_json(self) -> None:
        out = render.dumps(Workspace(id=1, name="auth"))
        assert json.loads(out)["name"] == "auth"

    def test_non_serializable_raises(self) -> None:
        with pytest.raises(TypeError, match="not JSON-serializable"):
            render.dumps(object())


class TestPrio:
    def test_zero_is_blank(self) -> None:
        assert render._prio(0) == "  "

    def test_nonzero(self) -> None:
        assert render._prio(3) == "P3"


class TestWorkspaces:
    def test_empty(self) -> None:
        assert render.workspaces([]) == "(no workspaces)"

    def test_singular_and_plural(self) -> None:
        out = render.workspaces([(Workspace(id=1, name="a"), 1), (Workspace(id=2, name="b"), 2)])
        assert "(1 track)" in out
        assert "(2 tracks)" in out


class TestFrontier:
    def test_empty(self) -> None:
        assert render.frontier([], {}) == "(nothing ready)"

    def test_status_name_used(self) -> None:
        out = render.frontier([Task(id=4, status_id=1, priority=2, title="do it")], {1: "todo"})
        assert "[todo]" in out and "do it" in out and "P2" in out

    def test_status_id_fallback_when_name_missing(self) -> None:
        out = render.frontier([Task(id=4, status_id=9, title="x")], {})
        assert "[9]" in out


class TestTaskDetail:
    def _detail(self, **task_over) -> dict:
        task = {"id": 1, "title": "build", "statusId": 1, "kindId": None, "priority": 0}
        task.update(task_over)
        return {"task": task}

    def test_kind_dash_when_none(self) -> None:
        out = render.task_detail(self._detail(), {1: "todo"}, {})
        assert "kind: -" in out

    def test_archived_flag(self) -> None:
        out = render.task_detail(self._detail(archived=True), {1: "todo"}, {})
        assert "ARCHIVED" in out

    def test_edges_and_relates_direction(self) -> None:
        detail = self._detail()
        detail["blocksIn"] = [2]
        detail["blocksOut"] = [3]
        detail["relates"] = [
            {"kind": "spawns", "otherTaskId": 5, "outgoing": True},
            {"kind": "mentions", "otherTaskId": 6, "outgoing": False},
        ]
        out = render.task_detail(detail, {1: "todo"}, {})
        assert "blocked-by: #2" in out
        assert "blocks: #3" in out
        assert "spawns→#5" in out
        assert "mentions←#6" in out


class TestTree:
    def test_empty_workspace(self) -> None:
        out = render.tree(Workspace(id=1, name="ws"), [], {})
        assert out.splitlines() == ["ws (#1)", "  (empty)"]

    def test_root_tasks_and_nested_segment(self) -> None:
        ws = Workspace(id=1, name="ws")
        track = Track(id=10, name="trk")
        root = Segment(id=100, track_id=10, parent_segment_id=None, name="(root)", is_root=True)
        child = Segment(id=101, track_id=10, parent_segment_id=100, name="api", is_root=False)
        root_task = Task(id=1, segment_id=100, status_id=1, title="root task")
        child_task = Task(id=2, segment_id=101, status_id=1, title="child task")
        out = render.tree(ws, [(track, [root, child], [root_task, child_task])], {1: "todo"})
        lines = out.splitlines()
        assert lines[0] == "ws (#1)"
        assert "▸ trk (#10)" in lines[1]
        # root-segment task hangs at depth 2 (directly under the track), child segment recurses.
        assert any("- #1" in ln and ln.startswith("    -") for ln in lines)
        assert any("▫ api (#101)" in ln for ln in lines)
        assert any("- #2 " in ln for ln in lines)
