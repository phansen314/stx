"""stxc/client.py — the wire client, exercised through a fake requests.Session (conftest)."""
from __future__ import annotations

import pytest

from conftest import FakeResponse, status_dict, task_dict
from stxc import StxApiError, StxConnError, StxError


class TestCall:
    def test_get_parses_json_and_builds(self, make_client) -> None:
        c = make_client([FakeResponse(200, {"items": [status_dict(id=2, name="doing")]})])
        out = c.statuses(7)
        assert c.s.last["method"] == "GET"
        assert c.s.last["url"] == "http://x:8420/workspaces/7/statuses"
        assert out[0].name == "doing"

    def test_non_2xx_raises_api_error_with_variant(self, make_client) -> None:
        c = make_client([FakeResponse(409, {"error": "VersionConflict", "message": "stale"})])
        with pytest.raises(StxApiError) as ei:
            c.task_detail(1)
        assert ei.value.code == 409
        assert ei.value.variant == "VersionConflict"
        assert "stale" in str(ei.value)

    def test_non_json_body_falls_back_to_text(self, make_client) -> None:
        c = make_client([FakeResponse(500, json_data=None, text="boom")])
        with pytest.raises(StxApiError) as ei:
            c.task_detail(1)
        assert ei.value.body == "boom"
        assert ei.value.variant is None

    def test_request_exception_maps_to_conn_error(self, make_client) -> None:
        c = make_client(raise_on_request=True)
        with pytest.raises(StxConnError) as ei:
            c.task_detail(1)
        assert isinstance(ei.value, StxError)  # both error kinds share the base
        assert ei.value.variant is None


class TestChanges:
    def test_parses_seq_and_schema(self, make_client) -> None:
        c = make_client([FakeResponse(200, {"seq": 42, "schema": 1})])
        assert c.changes() == (42, 1)
        assert c.s.last["url"] == "http://x:8420/changes"

    def test_unreachable_raises_conn_error(self, make_client) -> None:
        c = make_client(raise_on_request=True)
        with pytest.raises(StxConnError):
            c.changes()


class TestReads:
    def test_statuses_sorted_by_order_then_id(self, make_client) -> None:
        items = [status_dict(id=3, kanbanOrder=1), status_dict(id=1, kanbanOrder=0),
                 status_dict(id=2, kanbanOrder=0)]
        c = make_client([FakeResponse(200, {"items": items})])
        ids = [s.id for s in c.statuses(1)]
        assert ids == [1, 2, 3]  # (order,id): (0,1),(0,2),(1,3)

    def test_track_tasks_adds_status_query(self, make_client) -> None:
        c = make_client([FakeResponse(200, {"items": []})])
        c.track_tasks(5, status=2)
        assert c.s.last["url"] == "http://x:8420/tracks/5/tasks?status=2"

    def test_track_tasks_omits_query_when_no_status(self, make_client) -> None:
        c = make_client([FakeResponse(200, {"items": []})])
        c.track_tasks(5)
        assert c.s.last["url"] == "http://x:8420/tracks/5/tasks"

    def test_next_assembles_conditional_params(self, make_client) -> None:
        c = make_client([FakeResponse(200, {"items": []})])
        c.next(1, track=2, limit=10)
        assert c.s.last["url"] == "http://x:8420/next?workspace=1&track=2&limit=10"

    def test_next_minimal_params(self, make_client) -> None:
        c = make_client([FakeResponse(200, {"items": []})])
        c.next(9)
        assert c.s.last["url"] == "http://x:8420/next?workspace=9"

    def test_edges_bulk_read(self, make_client) -> None:
        body = {"blocks": [{"sourceTaskId": 1, "targetTaskId": 2}],
                "relates": [{"kind": "spawns", "sourceTaskId": 1, "targetTaskId": 3}]}
        c = make_client([FakeResponse(200, body)])
        assert c.edges(7) == body
        assert c.s.last["method"] == "GET"
        assert c.s.last["url"] == "http://x:8420/workspaces/7/edges"


class TestWrites:
    def test_create_task_via_segment_path_and_body(self, make_client) -> None:
        c = make_client([FakeResponse(200, task_dict(id=11))])
        c.create_task(segment=4, title="t", priority=2, status_id=3)
        call = c.s.last
        assert call["method"] == "POST"
        assert call["url"] == "http://x:8420/segments/4/tasks"
        assert call["json"] == {"title": "t", "description": "", "priority": 2, "statusId": 3}

    def test_create_task_via_track_path(self, make_client) -> None:
        c = make_client([FakeResponse(200, task_dict(id=12))])
        c.create_task(track=8, title="t")
        assert c.s.last["url"] == "http://x:8420/tracks/8/tasks"
        assert "statusId" not in c.s.last["json"]
        assert "kindId" not in c.s.last["json"]

    def test_move_status_body(self, make_client) -> None:
        c = make_client([FakeResponse(200, task_dict())])
        c.move_status(1, 2, 5)
        assert c.s.last["json"] == {"toStatusId": 2, "expectedVersion": 5}

    def test_edit_task_merges_expected_version(self, make_client) -> None:
        c = make_client([FakeResponse(200, task_dict())])
        c.edit_task(1, 3, title="new", clearKind=True)
        assert c.s.last["url"] == "http://x:8420/tasks/1"
        assert c.s.last["json"] == {"expectedVersion": 3, "title": "new", "clearKind": True}

    def test_create_segment_conditional_parent(self, make_client) -> None:
        c = make_client([FakeResponse(200, {"id": 1, "name": "s"})])
        c.create_segment(3, "s", parent_segment_id=9)
        assert c.s.last["json"] == {"name": "s", "parentSegmentId": 9}

    def test_archive_path(self, make_client) -> None:
        c = make_client([FakeResponse(200, {})])
        c.archive("tasks", 7)
        assert c.s.last["url"] == "http://x:8420/tasks/7/archive"

    def test_add_blocks_body(self, make_client) -> None:
        c = make_client([FakeResponse(200, {})])
        c.add_blocks(3, 9)
        assert c.s.last["url"] == "http://x:8420/blocks"
        assert c.s.last["json"] == {"sourceTaskId": 3, "targetTaskId": 9}

    def test_remove_blocks_hits_archive_route(self, make_client) -> None:
        c = make_client([FakeResponse(200, {})])
        c.remove_blocks(3, 9)
        assert c.s.last["method"] == "POST"
        assert c.s.last["url"] == "http://x:8420/blocks/archive"
        assert c.s.last["json"] == {"sourceTaskId": 3, "targetTaskId": 9}

    def test_remove_relates_includes_kind(self, make_client) -> None:
        c = make_client([FakeResponse(200, {})])
        c.remove_relates("mentions", 3, 9)
        assert c.s.last["url"] == "http://x:8420/relates/archive"
        assert c.s.last["json"] == {"kind": "mentions", "sourceTaskId": 3, "targetTaskId": 9}


class TestRegistry:
    def test_create_status_body(self, make_client) -> None:
        c = make_client([FakeResponse(200, status_dict(id=4, name="review"))])
        c.create_status(2, "review", 3, terminal=True)
        assert c.s.last["url"] == "http://x:8420/workspaces/2/statuses"
        assert c.s.last["json"] == {"name": "review", "kanbanOrder": 3, "terminal": True}

    def test_set_default_status_route(self, make_client) -> None:
        c = make_client([FakeResponse(200, {})])
        c.set_default_status(2, 5)
        assert c.s.last["method"] == "POST"
        assert c.s.last["url"] == "http://x:8420/workspaces/2/statuses/5/default"

    def test_archive_status_route(self, make_client) -> None:
        c = make_client([FakeResponse(200, {})])
        c.archive_status(2, 5)
        assert c.s.last["url"] == "http://x:8420/workspaces/2/statuses/5/archive"

    def test_create_kind_and_archive(self, make_client) -> None:
        c = make_client([FakeResponse(200, {"id": 9, "name": "bug"}), FakeResponse(200, {})])
        c.create_kind(2, "bug")
        assert c.s.last["url"] == "http://x:8420/workspaces/2/kinds"
        assert c.s.last["json"] == {"name": "bug"}
        c.archive_kind(2, 9)
        assert c.s.last["url"] == "http://x:8420/workspaces/2/kinds/9/archive"

    def test_create_transition_body(self, make_client) -> None:
        c = make_client([FakeResponse(200, {"id": 1, "fromStatusId": 1, "toStatusId": 2})])
        c.create_transition(2, 1, 2)
        assert c.s.last["url"] == "http://x:8420/workspaces/2/transitions"
        assert c.s.last["json"] == {"fromStatusId": 1, "toStatusId": 2}


class TestPing:
    def test_true_on_200(self, make_client) -> None:
        c = make_client([FakeResponse(200)])
        assert c.ping() is True

    def test_false_on_non_200(self, make_client) -> None:
        c = make_client([FakeResponse(503)])
        assert c.ping() is False

    def test_false_swallows_request_exception(self, make_client) -> None:
        c = make_client(raise_on_get=True)
        assert c.ping() is False
