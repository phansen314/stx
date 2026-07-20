"""HTTP client for the stx daemon — the same wire contract exercised by scripts/dev_sim.py,
wrapped in typed helpers that return the dataclasses in tui/models.py.

Non-2xx responses raise StxApiError carrying the daemon's typed error variant, so the UI can
branch on VersionConflict / IllegalTransition / Gone / etc.
"""
from __future__ import annotations

from typing import Any

import requests

from .models import Kind, Segment, Status, Task, Track, Transition, Workspace, _camel, build


def _camelize(changes: dict) -> dict:
    """Normalize edit_* kwargs to the wire's camelCase so snake_case keys aren't silently dropped."""
    return {_camel(k): v for k, v in changes.items()}


class StxError(Exception):
    """Base for every daemon-call failure so callers can `except StxError` once and catch both
    a typed API error and a transport/connection failure."""


class StxApiError(StxError):
    """The daemon answered with a non-2xx carrying a typed error variant."""

    def __init__(self, code: int, body: Any):
        self.code = code
        self.body = body
        self.variant = body.get("error") if isinstance(body, dict) else None
        msg = body.get("message") or self.variant if isinstance(body, dict) else str(body)
        super().__init__(f"{code} {self.variant or ''}: {msg}")


class StxConnError(StxError):
    """The daemon could not be reached (down, restarting, timed out). Carries no variant — it
    never made it to the daemon's error rails."""

    variant = None

    def __init__(self, cause: Exception):
        self.cause = cause
        super().__init__(f"daemon unreachable: {cause}")


class Client:
    def __init__(self, base_url: str = "http://127.0.0.1:8420"):
        self.base = base_url.rstrip("/")
        self.s = requests.Session()

    def _call(self, method: str, path: str, body: dict | None = None) -> Any:
        try:
            r = self.s.request(method, self.base + path, json=body, timeout=15)
        except requests.RequestException as e:
            # Connection refused / reset / timeout: the daemon is down or restarting. Raise a
            # typed transport error so the UI's `except StxError` path handles it instead of the
            # raw requests exception crashing the worker.
            raise StxConnError(e) from e
        try:
            data = r.json()
        except ValueError:
            data = r.text
        if not (200 <= r.status_code < 300):
            raise StxApiError(r.status_code, data)
        return data

    def ping(self) -> bool:
        try:
            return self.s.get(self.base + "/health", timeout=5).status_code == 200
        except requests.RequestException:
            return False

    def changes(self) -> tuple[int, int]:
        """Poll the daemon's change token: `(seq, schema)`. `seq` bumps on every committed write;
        compare by inequality (a daemon restart may reset it). Raises StxConnError if unreachable."""
        d = self._call("GET", "/changes")
        return int(d["seq"]), int(d["schema"])

    # ── reads ──
    def list_workspaces(self) -> list[Workspace]:
        return [build(Workspace, w) for w in self._call("GET", "/workspaces")["items"]]

    def statuses(self, ws: int) -> list[Status]:
        items = self._call("GET", f"/workspaces/{ws}/statuses")["items"]
        return sorted((build(Status, s) for s in items), key=lambda s: (s.kanban_order, s.id))

    def kinds(self, ws: int) -> list[Kind]:
        return [build(Kind, k) for k in self._call("GET", f"/workspaces/{ws}/kinds")["items"]]

    def relates_kinds(self, ws: int) -> list[str]:
        return self._call("GET", f"/workspaces/{ws}/relates-kinds")["items"]

    def transitions(self, ws: int) -> list[Transition]:
        return [build(Transition, t) for t in self._call("GET", f"/workspaces/{ws}/transitions")["items"]]

    def tracks(self, ws: int) -> list[Track]:
        return [build(Track, t) for t in self._call("GET", f"/workspaces/{ws}/tracks")["items"]]

    def segments(self, track: int) -> list[Segment]:
        return [build(Segment, s) for s in self._call("GET", f"/tracks/{track}/segments")["items"]]

    def track_tasks(self, track: int, status: int | None = None) -> list[Task]:
        q = f"?status={status}" if status is not None else ""
        return [build(Task, t) for t in self._call("GET", f"/tracks/{track}/tasks{q}")["items"]]

    def task_detail(self, task_id: int) -> dict:
        return self._call("GET", f"/tasks/{task_id}")

    def edges(self, ws: int) -> dict:
        """All live edges in a workspace: {"blocks": [...], "relates": [...]}. Bulk read for graph export."""
        return self._call("GET", f"/workspaces/{ws}/edges")

    def next(self, ws: int, track: int | None = None, segment: int | None = None,
             kind: int | None = None, limit: int | None = None) -> list[dict]:
        params = [f"workspace={ws}"]
        if track is not None:
            params.append(f"track={track}")
        if segment is not None:
            params.append(f"segment={segment}")
        if kind is not None:
            params.append(f"kind={kind}")
        if limit is not None:
            params.append(f"limit={limit}")
        return self._call("GET", "/next?" + "&".join(params))["items"]

    # ── writes ──
    def create_workspace(self, name: str) -> Workspace:
        return build(Workspace, self._call("POST", "/workspaces", {"name": name}))

    def create_track(self, ws: int, name: str, description: str = "") -> Track:
        return build(Track, self._call("POST", f"/workspaces/{ws}/tracks", {"name": name, "description": description}))

    def create_segment(self, track: int, name: str, parent_segment_id: int | None = None) -> Segment:
        body: dict = {"name": name}
        if parent_segment_id is not None:
            body["parentSegmentId"] = parent_segment_id
        return build(Segment, self._call("POST", f"/tracks/{track}/segments", body))

    def create_task(self, *, track: int | None = None, segment: int | None = None, title: str,
                    description: str = "", priority: int = 0, status_id: int | None = None,
                    kind_id: int | None = None) -> Task:
        body: dict = {"title": title, "description": description, "priority": priority}
        if status_id is not None:
            body["statusId"] = status_id
        if kind_id is not None:
            body["kindId"] = kind_id
        if segment is not None:
            return build(Task, self._call("POST", f"/segments/{segment}/tasks", body))
        return build(Task, self._call("POST", f"/tracks/{track}/tasks", body))

    def move_status(self, task_id: int, to_status_id: int, expected_version: int) -> Task:
        return build(Task, self._call("POST", f"/tasks/{task_id}/status",
                                      {"toStatusId": to_status_id, "expectedVersion": expected_version}))

    def edit_task(self, task_id: int, expected_version: int, **changes) -> Task:
        body = {"expectedVersion": expected_version, **_camelize(changes)}
        return build(Task, self._call("PATCH", f"/tasks/{task_id}", body))

    def edit_workspace(self, ws: int, expected_version: int, **changes) -> Workspace:
        body = {"expectedVersion": expected_version, **_camelize(changes)}
        return build(Workspace, self._call("PATCH", f"/workspaces/{ws}", body))

    def edit_track(self, track: int, expected_version: int, **changes) -> Track:
        body = {"expectedVersion": expected_version, **_camelize(changes)}
        return build(Track, self._call("PATCH", f"/tracks/{track}", body))

    # ── writes: registries (statuses / kinds / transitions) ──
    def create_status(self, ws: int, name: str, kanban_order: int, terminal: bool = False) -> Status:
        body = {"name": name, "kanbanOrder": kanban_order, "terminal": terminal}
        return build(Status, self._call("POST", f"/workspaces/{ws}/statuses", body))

    def set_default_status(self, ws: int, status_id: int) -> None:
        self._call("POST", f"/workspaces/{ws}/statuses/{status_id}/default")

    def archive_status(self, ws: int, status_id: int) -> None:
        self._call("POST", f"/workspaces/{ws}/statuses/{status_id}/archive")

    def create_kind(self, ws: int, name: str) -> Kind:
        return build(Kind, self._call("POST", f"/workspaces/{ws}/kinds", {"name": name}))

    def archive_kind(self, ws: int, kind_id: int) -> None:
        self._call("POST", f"/workspaces/{ws}/kinds/{kind_id}/archive")

    def create_transition(self, ws: int, from_status_id: int, to_status_id: int) -> Transition:
        body = {"fromStatusId": from_status_id, "toStatusId": to_status_id}
        return build(Transition, self._call("POST", f"/workspaces/{ws}/transitions", body))

    # ── writes: edges (drive the `next` frontier) ──
    def add_blocks(self, source_task_id: int, target_task_id: int) -> dict:
        return self._call("POST", "/blocks", {"sourceTaskId": source_task_id, "targetTaskId": target_task_id})

    def add_relates(self, kind: str, source_task_id: int, target_task_id: int) -> dict:
        return self._call("POST", "/relates",
                          {"kind": kind, "sourceTaskId": source_task_id, "targetTaskId": target_task_id})

    def remove_blocks(self, source_task_id: int, target_task_id: int) -> dict:
        return self._call("POST", "/blocks/archive",
                          {"sourceTaskId": source_task_id, "targetTaskId": target_task_id})

    def remove_relates(self, kind: str, source_task_id: int, target_task_id: int) -> dict:
        return self._call("POST", "/relates/archive",
                          {"kind": kind, "sourceTaskId": source_task_id, "targetTaskId": target_task_id})

    def archive(self, kind: str, entity_id: int) -> None:
        # kind in {tasks, segments, tracks, workspaces}
        self._call("POST", f"/{kind}/{entity_id}/archive")
