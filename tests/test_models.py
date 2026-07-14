"""stxc/models.py — the wire→dataclass parser (_snake, build). Pure, stdlib-only."""
from __future__ import annotations

from stxc.models import Segment, Status, Task, Workspace, _snake, build


class TestSnake:
    def test_camel_to_snake(self) -> None:
        assert _snake("workspaceId") == "workspace_id"
        assert _snake("kanbanOrder") == "kanban_order"
        assert _snake("parentSegmentId") == "parent_segment_id"

    def test_already_snake_or_single_word(self) -> None:
        assert _snake("id") == "id"
        assert _snake("name") == "name"

    def test_leading_capital_not_prefixed_with_underscore(self) -> None:
        # The (?<!^) guard means a leading capital is not given a leading "_".
        assert _snake("Title") == "title"


class TestBuild:
    def test_maps_camelcase_keys(self) -> None:
        ws = build(Workspace, {"id": 7, "name": "auth", "metadataJson": "{}"})
        assert ws.id == 7
        assert ws.name == "auth"
        assert ws.metadata_json == "{}"

    def test_ignores_unknown_keys(self) -> None:
        # The daemon may add fields the client doesn't model — they must be dropped, not crash.
        t = build(Task, {"id": 3, "title": "x", "somethingNew": 99, "deeplyNested": {"a": 1}})
        assert t.id == 3
        assert t.title == "x"

    def test_partial_payload_uses_defaults(self) -> None:
        # Frontier rows are partial dicts; missing fields fall back to dataclass defaults.
        t = build(Task, {"id": 5, "statusId": 2, "priority": 1})
        assert (t.id, t.status_id, t.priority) == (5, 2, 1)
        assert t.title == ""
        assert t.kind_id is None

    def test_empty_payload_is_all_defaults(self) -> None:
        s = build(Status, {})
        assert s.id == 0 and s.name == "" and s.terminal is False

    def test_nullable_field_passes_through(self) -> None:
        seg = build(Segment, {"id": 1, "parentSegmentId": None, "isRoot": True})
        assert seg.parent_segment_id is None
        assert seg.is_root is True
