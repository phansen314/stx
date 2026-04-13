from __future__ import annotations

import dataclasses
import json
import re
import sqlite3
from typing import Any

from .mappers import (
    row_to_edge_list_item,
    row_to_group,
    row_to_journal_entry,
    row_to_status,
    row_to_tag,
    row_to_task,
    row_to_workspace,
)
from .models import (
    EntityType,
    Group,
    JournalEntry,
    NewGroup,
    NewJournalEntry,
    NewStatus,
    NewTag,
    NewTask,
    NewWorkspace,
    Status,
    Tag,
    Task,
    TaskFilter,
    Workspace,
)
from .service_models import EdgeListItem

# ---- Updatable-field allowlists ----

_WORKSPACE_UPDATABLE: frozenset[str] = frozenset({"name", "archived"})
_STATUS_UPDATABLE: frozenset[str] = frozenset({"name", "archived"})
_TASK_UPDATABLE: frozenset[str] = frozenset(
    {
        "title",
        "description",
        "status_id",
        "group_id",
        "priority",
        "due_date",
        "position",
        "archived",
        "start_date",
        "finish_date",
    }
)
_TAG_UPDATABLE: frozenset[str] = frozenset({"name", "archived"})
_GROUP_UPDATABLE: frozenset[str] = frozenset(
    {
        "title",
        "description",
        "parent_id",
        "position",
        "archived",
    }
)


# ---- Internal helpers ----


_SAFE_COLUMN_RE = re.compile(r"^[a-z_]+$")


def _build_update(
    table: str,
    row_id: int,
    changes: dict[str, Any],
    allowed: frozenset[str],
) -> tuple[str, tuple[Any, ...]]:
    if not changes:
        raise ValueError("changes must not be empty")
    bad = changes.keys() - allowed
    if bad:
        raise ValueError(f"disallowed fields: {', '.join(sorted(bad))}")
    for k in changes:
        if not _SAFE_COLUMN_RE.match(k):
            raise ValueError(f"invalid column name: {k!r}")
    set_clause = ", ".join(f"{k} = ?" for k in changes)
    params = (*changes.values(), row_id)
    return f"UPDATE {table} SET {set_clause} WHERE id = ?", params


def _asdict_for_insert(obj: object) -> dict[str, Any]:
    return {f.name: getattr(obj, f.name) for f in dataclasses.fields(obj)}  # type: ignore[arg-type]


# ---- Workspace functions ----


def insert_workspace(conn: sqlite3.Connection, new: NewWorkspace) -> Workspace:
    d = _asdict_for_insert(new)
    cur = conn.execute("INSERT INTO workspaces (name) VALUES (:name)", d)
    row = conn.execute("SELECT * FROM workspaces WHERE id = ?", (cur.lastrowid,)).fetchone()
    return row_to_workspace(row)


def get_workspace(conn: sqlite3.Connection, workspace_id: int) -> Workspace | None:
    row = conn.execute("SELECT * FROM workspaces WHERE id = ?", (workspace_id,)).fetchone()
    return row_to_workspace(row) if row else None


def get_workspace_by_name(conn: sqlite3.Connection, name: str) -> Workspace | None:
    row = conn.execute(
        "SELECT * FROM workspaces WHERE name = ? AND archived = 0", (name,)
    ).fetchone()
    return row_to_workspace(row) if row else None


def list_workspaces(
    conn: sqlite3.Connection,
    *,
    include_archived: bool = False,
    only_archived: bool = False,
) -> tuple[Workspace, ...]:
    if only_archived:
        archive_clause = " WHERE archived = 1"
    elif include_archived:
        archive_clause = ""
    else:
        archive_clause = " WHERE archived = 0"
    rows = conn.execute(f"SELECT * FROM workspaces{archive_clause} ORDER BY created_at").fetchall()
    return tuple(row_to_workspace(r) for r in rows)


def update_workspace(
    conn: sqlite3.Connection,
    workspace_id: int,
    changes: dict[str, Any],
) -> Workspace:
    sql, params = _build_update("workspaces", workspace_id, changes, _WORKSPACE_UPDATABLE)
    cur = conn.execute(sql, params)
    if cur.rowcount == 0:
        raise LookupError(f"workspace {workspace_id} not found")
    row = conn.execute("SELECT * FROM workspaces WHERE id = ?", (workspace_id,)).fetchone()
    return row_to_workspace(row)


# ---- Status functions ----


def insert_status(conn: sqlite3.Connection, new: NewStatus) -> Status:
    d = _asdict_for_insert(new)
    cur = conn.execute(
        "INSERT INTO statuses (workspace_id, name) VALUES (:workspace_id, :name)",
        d,
    )
    row = conn.execute("SELECT * FROM statuses WHERE id = ?", (cur.lastrowid,)).fetchone()
    return row_to_status(row)


def get_status_by_name(
    conn: sqlite3.Connection,
    workspace_id: int,
    name: str,
) -> Status | None:
    row = conn.execute(
        "SELECT * FROM statuses WHERE workspace_id = ? AND name = ? AND archived = 0",
        (workspace_id, name),
    ).fetchone()
    return row_to_status(row) if row else None


def get_status(conn: sqlite3.Connection, status_id: int) -> Status | None:
    row = conn.execute("SELECT * FROM statuses WHERE id = ?", (status_id,)).fetchone()
    return row_to_status(row) if row else None


def list_statuses(
    conn: sqlite3.Connection,
    workspace_id: int,
    *,
    include_archived: bool = False,
    only_archived: bool = False,
) -> tuple[Status, ...]:
    if only_archived:
        archive_clause = " AND archived = 1"
    elif include_archived:
        archive_clause = ""
    else:
        archive_clause = " AND archived = 0"
    rows = conn.execute(
        f"SELECT * FROM statuses WHERE workspace_id = ?{archive_clause} ORDER BY name, id",
        (workspace_id,),
    ).fetchall()
    return tuple(row_to_status(r) for r in rows)


def update_status(
    conn: sqlite3.Connection,
    status_id: int,
    changes: dict[str, Any],
) -> Status:
    sql, params = _build_update("statuses", status_id, changes, _STATUS_UPDATABLE)
    cur = conn.execute(sql, params)
    if cur.rowcount == 0:
        raise LookupError(f"status {status_id} not found")
    row = conn.execute("SELECT * FROM statuses WHERE id = ?", (status_id,)).fetchone()
    return row_to_status(row)


# ---- Task functions ----


def insert_task(conn: sqlite3.Connection, new: NewTask) -> Task:
    d = _asdict_for_insert(new)
    cur = conn.execute(
        "INSERT INTO tasks "
        "(workspace_id, title, status_id, description, priority, due_date, position, start_date, finish_date, group_id) "
        "VALUES (:workspace_id, :title, :status_id, :description, :priority, :due_date, :position, :start_date, :finish_date, :group_id)",
        d,
    )
    row = conn.execute("SELECT * FROM tasks WHERE id = ?", (cur.lastrowid,)).fetchone()
    return row_to_task(row)


def get_task(conn: sqlite3.Connection, task_id: int) -> Task | None:
    row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    return row_to_task(row) if row else None


def get_task_by_title(
    conn: sqlite3.Connection,
    workspace_id: int,
    title: str,
) -> Task | None:
    row = conn.execute(
        "SELECT * FROM tasks WHERE workspace_id = ? AND title = ? AND archived = 0",
        (workspace_id, title),
    ).fetchone()
    return row_to_task(row) if row else None


def list_tasks(
    conn: sqlite3.Connection,
    workspace_id: int,
    *,
    include_archived: bool = False,
) -> tuple[Task, ...]:
    archive_clause = "" if include_archived else " AND archived = 0"
    rows = conn.execute(
        f"SELECT * FROM tasks WHERE workspace_id = ?{archive_clause} ORDER BY position, id",
        (workspace_id,),
    ).fetchall()
    return tuple(row_to_task(r) for r in rows)


def list_tasks_by_status(
    conn: sqlite3.Connection,
    status_id: int,
    *,
    include_archived: bool = False,
) -> tuple[Task, ...]:
    archive_clause = "" if include_archived else " AND archived = 0"
    rows = conn.execute(
        f"SELECT * FROM tasks WHERE status_id = ?{archive_clause} ORDER BY position, id",
        (status_id,),
    ).fetchall()
    return tuple(row_to_task(r) for r in rows)


def list_tasks_filtered(
    conn: sqlite3.Connection,
    workspace_id: int,
    *,
    task_filter: TaskFilter | None = None,
) -> tuple[Task, ...]:
    clauses = ["workspace_id = ?"]
    params: list[object] = [workspace_id]
    f = task_filter or TaskFilter()
    if f.only_archived:
        clauses.append("archived = 1")
    elif not f.include_archived:
        clauses.append("archived = 0")
    if f.status_id is not None:
        clauses.append("status_id = ?")
        params.append(f.status_id)
    if f.priority is not None:
        clauses.append("priority = ?")
        params.append(f.priority)
    if f.search is not None:
        clauses.append("title LIKE ?")
        params.append(f"%{f.search}%")
    if f.tag_id is not None:
        clauses.append("id IN (SELECT task_id FROM task_tags WHERE tag_id = ?)")
        params.append(f.tag_id)
    if f.group_id is not None:
        clauses.append("group_id = ?")
        params.append(f.group_id)
    where = " AND ".join(clauses)
    rows = conn.execute(
        f"SELECT * FROM tasks WHERE {where} ORDER BY position, id",
        params,
    ).fetchall()
    return tuple(row_to_task(r) for r in rows)


def update_task(
    conn: sqlite3.Connection,
    task_id: int,
    changes: dict[str, Any],
) -> Task:
    sql, params = _build_update("tasks", task_id, changes, _TASK_UPDATABLE)
    cur = conn.execute(sql, params)
    if cur.rowcount == 0:
        raise LookupError(f"task {task_id} not found")
    row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    return row_to_task(row)


def list_tasks_by_ids(
    conn: sqlite3.Connection,
    task_ids: tuple[int, ...],
) -> tuple[Task, ...]:
    """Return tasks for the given IDs in a single query."""
    if not task_ids:
        return ()
    placeholders = ",".join("?" * len(task_ids))
    rows = conn.execute(
        f"SELECT * FROM tasks WHERE id IN ({placeholders})",
        task_ids,
    ).fetchall()
    return tuple(row_to_task(r) for r in rows)


# ---- Task metadata functions ----


# Allowlist of tables that carry a `metadata` JSON column, mapped to the
# singular entity name used in LookupError messages. Table names are
# interpolated into SQL (not parameter-bound) in the generic helpers below,
# so every caller goes through a public wrapper that pins its table literal.
_METADATA_TABLES: dict[str, str] = {
    "tasks": "task",
    "workspaces": "workspace",
    "groups": "group",
}


def _set_metadata_key(
    conn: sqlite3.Connection,
    table: str,
    entity_id: int,
    key: str,
    value: str,
) -> None:
    """Set a single metadata key via SQLite json_set. Creates or overwrites.

    Callers must pre-validate the key (see service._normalize_meta_key); the
    slug charset enforced there excludes characters that could escape the
    quoted JSON path literal built below.
    """
    if table not in _METADATA_TABLES:
        raise ValueError(f"invalid metadata table: {table!r}")
    path = f'$."{key}"'
    cur = conn.execute(
        f"UPDATE {table} SET metadata = json_set(metadata, ?, ?) WHERE id = ?",
        (path, value, entity_id),
    )
    if cur.rowcount == 0:
        raise LookupError(f"{_METADATA_TABLES[table]} {entity_id} not found")


def _remove_metadata_key(
    conn: sqlite3.Connection,
    table: str,
    entity_id: int,
    key: str,
) -> None:
    """Remove a single metadata key via SQLite json_remove."""
    if table not in _METADATA_TABLES:
        raise ValueError(f"invalid metadata table: {table!r}")
    path = f'$."{key}"'
    cur = conn.execute(
        f"UPDATE {table} SET metadata = json_remove(metadata, ?) WHERE id = ?",
        (path, entity_id),
    )
    if cur.rowcount == 0:
        raise LookupError(f"{_METADATA_TABLES[table]} {entity_id} not found")


def _copy_metadata(
    conn: sqlite3.Connection,
    table: str,
    src_id: int,
    dst_id: int,
) -> None:
    """Copy the entire metadata blob from src to dst within the same table."""
    if table not in _METADATA_TABLES:
        raise ValueError(f"invalid metadata table: {table!r}")
    cur = conn.execute(
        f"UPDATE {table} SET metadata = (SELECT metadata FROM {table} WHERE id = ?) WHERE id = ?",
        (src_id, dst_id),
    )
    if cur.rowcount == 0:
        raise LookupError(f"{_METADATA_TABLES[table]} {dst_id} not found")


def _replace_metadata(
    conn: sqlite3.Connection,
    table: str,
    entity_id: int,
    metadata_json: str,
) -> None:
    """Atomically replace the entire metadata blob. Caller must supply a
    pre-serialized JSON object string; validity is enforced by the column's
    CHECK (json_valid(metadata)) constraint."""
    if table not in _METADATA_TABLES:
        raise ValueError(f"invalid metadata table: {table!r}")
    cur = conn.execute(
        f"UPDATE {table} SET metadata = ? WHERE id = ?",
        (metadata_json, entity_id),
    )
    if cur.rowcount == 0:
        raise LookupError(f"{_METADATA_TABLES[table]} {entity_id} not found")


# ---- Per-entity public wrappers ----


def set_task_metadata_key(conn: sqlite3.Connection, task_id: int, key: str, value: str) -> None:
    _set_metadata_key(conn, "tasks", task_id, key, value)


def remove_task_metadata_key(conn: sqlite3.Connection, task_id: int, key: str) -> None:
    _remove_metadata_key(conn, "tasks", task_id, key)


def copy_task_metadata(conn: sqlite3.Connection, src_task_id: int, dst_task_id: int) -> None:
    """Used when a task moves between workspaces — the destination is a fresh
    row with empty metadata, and we want a byte-for-byte copy of the source.
    """
    _copy_metadata(conn, "tasks", src_task_id, dst_task_id)


def replace_task_metadata(conn: sqlite3.Connection, task_id: int, metadata_json: str) -> None:
    _replace_metadata(conn, "tasks", task_id, metadata_json)


def set_workspace_metadata_key(
    conn: sqlite3.Connection, workspace_id: int, key: str, value: str
) -> None:
    _set_metadata_key(conn, "workspaces", workspace_id, key, value)


def remove_workspace_metadata_key(conn: sqlite3.Connection, workspace_id: int, key: str) -> None:
    _remove_metadata_key(conn, "workspaces", workspace_id, key)


def replace_workspace_metadata(
    conn: sqlite3.Connection, workspace_id: int, metadata_json: str
) -> None:
    _replace_metadata(conn, "workspaces", workspace_id, metadata_json)


def set_group_metadata_key(conn: sqlite3.Connection, group_id: int, key: str, value: str) -> None:
    _set_metadata_key(conn, "groups", group_id, key, value)


def remove_group_metadata_key(conn: sqlite3.Connection, group_id: int, key: str) -> None:
    _remove_metadata_key(conn, "groups", group_id, key)


def replace_group_metadata(conn: sqlite3.Connection, group_id: int, metadata_json: str) -> None:
    _replace_metadata(conn, "groups", group_id, metadata_json)


# ---- Edge metadata helpers (composite PK: from_type, from_id, to_type, to_id, kind) ----


def get_edge_metadata(
    conn: sqlite3.Connection,
    from_type: str,
    from_id: int,
    to_type: str,
    to_id: int,
    kind: str,
) -> dict[str, str]:
    row = conn.execute(
        "SELECT metadata FROM edges "
        "WHERE from_type = ? AND from_id = ? AND to_type = ? AND to_id = ? AND kind = ? AND archived = 0",
        (from_type, from_id, to_type, to_id, kind),
    ).fetchone()
    if row is None:
        raise LookupError(f"edge ({from_type}:{from_id} → {to_type}:{to_id} [{kind}]) not found")
    return json.loads(row["metadata"])


def get_edge_workspace_id(
    conn: sqlite3.Connection,
    from_type: str,
    from_id: int,
    to_type: str,
    to_id: int,
    kind: str,
) -> int:
    row = conn.execute(
        "SELECT workspace_id FROM edges "
        "WHERE from_type = ? AND from_id = ? AND to_type = ? AND to_id = ? AND kind = ? AND archived = 0",
        (from_type, from_id, to_type, to_id, kind),
    ).fetchone()
    if row is None:
        raise LookupError(f"edge ({from_type}:{from_id} → {to_type}:{to_id} [{kind}]) not found")
    return row["workspace_id"]


def set_edge_metadata_key(
    conn: sqlite3.Connection,
    from_type: str,
    from_id: int,
    to_type: str,
    to_id: int,
    kind: str,
    key: str,
    value: str,
) -> None:
    path = f'$."{key}"'
    cur = conn.execute(
        "UPDATE edges SET metadata = json_set(metadata, ?, ?) "
        "WHERE from_type = ? AND from_id = ? AND to_type = ? AND to_id = ? AND kind = ? AND archived = 0",
        (path, value, from_type, from_id, to_type, to_id, kind),
    )
    if cur.rowcount == 0:
        raise LookupError(f"edge ({from_type}:{from_id} → {to_type}:{to_id} [{kind}]) not found")


def remove_edge_metadata_key(
    conn: sqlite3.Connection,
    from_type: str,
    from_id: int,
    to_type: str,
    to_id: int,
    kind: str,
    key: str,
) -> None:
    path = f'$."{key}"'
    cur = conn.execute(
        "UPDATE edges SET metadata = json_remove(metadata, ?) "
        "WHERE from_type = ? AND from_id = ? AND to_type = ? AND to_id = ? AND kind = ? AND archived = 0",
        (path, from_type, from_id, to_type, to_id, kind),
    )
    if cur.rowcount == 0:
        raise LookupError(f"edge ({from_type}:{from_id} → {to_type}:{to_id} [{kind}]) not found")


def replace_edge_metadata(
    conn: sqlite3.Connection,
    from_type: str,
    from_id: int,
    to_type: str,
    to_id: int,
    kind: str,
    metadata_json: str,
) -> None:
    cur = conn.execute(
        "UPDATE edges SET metadata = ? "
        "WHERE from_type = ? AND from_id = ? AND to_type = ? AND to_id = ? AND kind = ? AND archived = 0",
        (metadata_json, from_type, from_id, to_type, to_id, kind),
    )
    if cur.rowcount == 0:
        raise LookupError(f"edge ({from_type}:{from_id} → {to_type}:{to_id} [{kind}]) not found")


# ---- Unified edge functions ----

# Nodes CTE: union of all node types for title lookups in edge queries.
# Used by list_edges_by_workspace and the hydrated edge queries.
_NODES_CTE = """
WITH nodes AS (
    SELECT id, workspace_id, title, 'task' AS node_type FROM tasks WHERE archived = 0
    UNION ALL
    SELECT id, workspace_id, title, 'group' AS node_type FROM groups WHERE archived = 0
    UNION ALL
    SELECT id, id AS workspace_id, name AS title, 'workspace' AS node_type FROM workspaces WHERE archived = 0
)
"""


def add_edge(
    conn: sqlite3.Connection,
    from_type: str,
    from_id: int,
    to_type: str,
    to_id: int,
    workspace_id: int,
    kind: str,
    acyclic: int = 0,
) -> None:
    conn.execute(
        "INSERT INTO edges (from_type, from_id, to_type, to_id, workspace_id, kind, acyclic) "
        "VALUES (?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT (from_type, from_id, to_type, to_id, kind) "
        "DO UPDATE SET archived = 0, acyclic = excluded.acyclic, metadata = '{}'",
        (from_type, from_id, to_type, to_id, workspace_id, kind, acyclic),
    )


def archive_edge(
    conn: sqlite3.Connection,
    from_type: str,
    from_id: int,
    to_type: str,
    to_id: int,
    kind: str,
) -> None:
    conn.execute(
        "UPDATE edges SET archived = 1 "
        "WHERE from_type = ? AND from_id = ? AND to_type = ? AND to_id = ? AND kind = ? AND archived = 0",
        (from_type, from_id, to_type, to_id, kind),
    )


def get_active_edge(
    conn: sqlite3.Connection,
    from_type: str,
    from_id: int,
    to_type: str,
    to_id: int,
    kind: str,
) -> tuple[str, int] | None:
    """Return (kind, acyclic) of an active edge, or None if not found."""
    row = conn.execute(
        "SELECT kind, acyclic FROM edges "
        "WHERE from_type = ? AND from_id = ? AND to_type = ? AND to_id = ? AND kind = ? AND archived = 0",
        (from_type, from_id, to_type, to_id, kind),
    ).fetchone()
    return (row["kind"], row["acyclic"]) if row is not None else None


def get_archived_edge(
    conn: sqlite3.Connection,
    from_type: str,
    from_id: int,
    to_type: str,
    to_id: int,
    kind: str,
) -> tuple[str, int] | None:
    """Return (kind, acyclic) of an archived edge, or None if not found."""
    row = conn.execute(
        "SELECT kind, acyclic FROM edges "
        "WHERE from_type = ? AND from_id = ? AND to_type = ? AND to_id = ? AND kind = ? AND archived = 1",
        (from_type, from_id, to_type, to_id, kind),
    ).fetchone()
    return (row["kind"], row["acyclic"]) if row is not None else None


def list_edge_targets_from(
    conn: sqlite3.Connection,
    from_type: str,
    from_id: int,
) -> tuple[tuple[str, int], ...]:
    """Return (to_type, to_id) pairs for all active edges originating at (from_type, from_id)
    whose target endpoint is also active. Archived edges and archived endpoints are
    hidden so this function agrees with the hydrated variant and with list_edges_by_workspace."""
    rows = conn.execute(
        _NODES_CTE + """
        SELECT e.to_type, e.to_id
        FROM edges e
        JOIN nodes n ON n.node_type = e.to_type AND n.id = e.to_id
        WHERE e.from_type = ? AND e.from_id = ? AND e.archived = 0
        """,
        (from_type, from_id),
    ).fetchall()
    return tuple((r["to_type"], r["to_id"]) for r in rows)


def list_edge_sources_into(
    conn: sqlite3.Connection,
    to_type: str,
    to_id: int,
) -> tuple[tuple[str, int], ...]:
    """Return (from_type, from_id) pairs for all active edges pointing into (to_type, to_id)
    whose source endpoint is also active. Archived edges and archived endpoints are
    hidden so this function agrees with the hydrated variant and with list_edges_by_workspace."""
    rows = conn.execute(
        _NODES_CTE + """
        SELECT e.from_type, e.from_id
        FROM edges e
        JOIN nodes n ON n.node_type = e.from_type AND n.id = e.from_id
        WHERE e.to_type = ? AND e.to_id = ? AND e.archived = 0
        """,
        (to_type, to_id),
    ).fetchall()
    return tuple((r["from_type"], r["from_id"]) for r in rows)


def list_edge_targets_from_hydrated(
    conn: sqlite3.Connection,
    from_type: str,
    from_id: int,
) -> tuple[tuple[str, int, str, str], ...]:
    """Return (to_type, to_id, to_title, kind) for active edges from (from_type, from_id).
    Archived edges and archived endpoints are excluded."""
    rows = conn.execute(
        _NODES_CTE + """
        SELECT e.to_type, e.to_id, n.title AS to_title, e.kind
        FROM edges e
        JOIN nodes n ON n.node_type = e.to_type AND n.id = e.to_id
        WHERE e.from_type = ? AND e.from_id = ? AND e.archived = 0
        """,
        (from_type, from_id),
    ).fetchall()
    return tuple((r["to_type"], r["to_id"], r["to_title"], r["kind"]) for r in rows)


def list_edge_sources_into_hydrated(
    conn: sqlite3.Connection,
    to_type: str,
    to_id: int,
) -> tuple[tuple[str, int, str, str], ...]:
    """Return (from_type, from_id, from_title, kind) for active edges pointing into (to_type, to_id).
    Archived edges and archived endpoints are excluded."""
    rows = conn.execute(
        _NODES_CTE + """
        SELECT e.from_type, e.from_id, n.title AS from_title, e.kind
        FROM edges e
        JOIN nodes n ON n.node_type = e.from_type AND n.id = e.from_id
        WHERE e.to_type = ? AND e.to_id = ? AND e.archived = 0
        """,
        (to_type, to_id),
    ).fetchall()
    return tuple((r["from_type"], r["from_id"], r["from_title"], r["kind"]) for r in rows)


def list_all_edge_rows(
    conn: sqlite3.Connection,
) -> tuple[dict, ...]:
    """Return all edges rows as plain dicts (full columns preserved)."""
    rows = conn.execute(
        "SELECT from_type, from_id, to_type, to_id, workspace_id, kind, acyclic, archived, metadata FROM edges"
    ).fetchall()
    return tuple(
        {
            "from_type": r["from_type"],
            "from_id": r["from_id"],
            "to_type": r["to_type"],
            "to_id": r["to_id"],
            "workspace_id": r["workspace_id"],
            "kind": r["kind"],
            "acyclic": bool(r["acyclic"]),
            "archived": bool(r["archived"]),
            "metadata": json.loads(r["metadata"]),
        }
        for r in rows
    )


def list_edges_by_workspace(
    conn: sqlite3.Connection,
    workspace_id: int,
    *,
    kind: str | None = None,
    from_type: str | None = None,
    from_id: int | None = None,
    to_type: str | None = None,
    to_id: int | None = None,
) -> tuple[EdgeListItem, ...]:
    """Return active edges for a workspace, optionally filtered by kind and/or node.

    Endpoint nodes are filtered via the nodes CTE (archived=0) — archived
    entities stay hidden across the codebase.

    NOTE: ``clauses`` holds only statically-authored SQL fragments. All
    user-supplied values go through ``params``; never append user input to
    the clauses list.
    """
    clauses = ["e.workspace_id = ?", "e.archived = 0"]
    params: list[Any] = [workspace_id]
    if kind is not None:
        clauses.append("e.kind = ?")
        params.append(kind)
    if from_type is not None and from_id is not None:
        clauses.append("e.from_type = ? AND e.from_id = ?")
        params.extend([from_type, from_id])
    if to_type is not None and to_id is not None:
        clauses.append("e.to_type = ? AND e.to_id = ?")
        params.extend([to_type, to_id])
    where = " AND ".join(clauses)
    rows = conn.execute(
        _NODES_CTE + f"""
        SELECT e.from_type, e.from_id, nf.title AS from_title,
               e.to_type, e.to_id, nt.title AS to_title,
               e.workspace_id, e.kind, e.acyclic
        FROM edges e
        JOIN nodes nf ON nf.node_type = e.from_type AND nf.id = e.from_id
        JOIN nodes nt ON nt.node_type = e.to_type AND nt.id = e.to_id
        WHERE {where}
        ORDER BY e.from_type, e.from_id, e.to_type, e.to_id, e.kind
        """,
        params,
    ).fetchall()
    return tuple(row_to_edge_list_item(r) for r in rows)


def get_reachable_nodes(
    conn: sqlite3.Connection,
    from_type: str,
    from_id: int,
) -> set[tuple[str, int]]:
    """Return all (node_type, node_id) reachable from (from_type, from_id)
    following active acyclic edges transitively. Used for cycle detection:
    if (A_type, A_id) in get_reachable_nodes(B_type, B_id), then adding
    edge B→A would create a cycle."""
    rows = conn.execute(
        """
        WITH RECURSIVE reachable(to_type, to_id) AS (
            SELECT to_type, to_id FROM edges
            WHERE from_type = ? AND from_id = ? AND acyclic = 1 AND archived = 0
            UNION
            SELECT e.to_type, e.to_id FROM edges e
            JOIN reachable r ON e.from_type = r.to_type AND e.from_id = r.to_id
            WHERE e.acyclic = 1 AND e.archived = 0
        )
        SELECT to_type, to_id FROM reachable
        """,
        (from_type, from_id),
    ).fetchall()
    return {(r["to_type"], r["to_id"]) for r in rows}


def list_all_task_tags(
    conn: sqlite3.Connection,
) -> tuple[dict, ...]:
    """Return all task_tags rows as plain dicts (full FK columns preserved)."""
    rows = conn.execute("SELECT task_id, tag_id, workspace_id FROM task_tags").fetchall()
    return tuple(
        {"task_id": r["task_id"], "tag_id": r["tag_id"], "workspace_id": r["workspace_id"]}
        for r in rows
    )


# ---- Journal functions ----


def insert_journal_entry(
    conn: sqlite3.Connection,
    new: NewJournalEntry,
) -> JournalEntry:
    d = _asdict_for_insert(new)
    cur = conn.execute(
        "INSERT INTO journal (entity_type, entity_id, workspace_id, field, old_value, new_value, source) "
        "VALUES (:entity_type, :entity_id, :workspace_id, :field, :old_value, :new_value, :source)",
        d,
    )
    row = conn.execute("SELECT * FROM journal WHERE id = ?", (cur.lastrowid,)).fetchone()
    return row_to_journal_entry(row)


def list_journal(
    conn: sqlite3.Connection,
    entity_type: EntityType,
    entity_id: int,
) -> tuple[JournalEntry, ...]:
    rows = conn.execute(
        "SELECT * FROM journal WHERE entity_type = ? AND entity_id = ? ORDER BY changed_at DESC, id DESC",
        (entity_type, entity_id),
    ).fetchall()
    return tuple(row_to_journal_entry(r) for r in rows)


def list_all_journal(
    conn: sqlite3.Connection,
) -> tuple[JournalEntry, ...]:
    """Return all journal rows ordered by workspace and time."""
    rows = conn.execute("SELECT * FROM journal ORDER BY workspace_id, changed_at, id").fetchall()
    return tuple(row_to_journal_entry(r) for r in rows)


# ---- Tag functions ----


def insert_tag(conn: sqlite3.Connection, new: NewTag) -> Tag:
    d = _asdict_for_insert(new)
    cur = conn.execute(
        "INSERT INTO tags (workspace_id, name) VALUES (:workspace_id, :name)",
        d,
    )
    row = conn.execute("SELECT * FROM tags WHERE id = ?", (cur.lastrowid,)).fetchone()
    return row_to_tag(row)


def get_tag(conn: sqlite3.Connection, tag_id: int) -> Tag | None:
    row = conn.execute("SELECT * FROM tags WHERE id = ?", (tag_id,)).fetchone()
    return row_to_tag(row) if row else None


def get_tag_by_name(
    conn: sqlite3.Connection,
    workspace_id: int,
    name: str,
) -> Tag | None:
    row = conn.execute(
        "SELECT * FROM tags WHERE workspace_id = ? AND name = ? AND archived = 0",
        (workspace_id, name),
    ).fetchone()
    return row_to_tag(row) if row else None


def list_tags(
    conn: sqlite3.Connection,
    workspace_id: int,
    *,
    include_archived: bool = False,
    only_archived: bool = False,
) -> tuple[Tag, ...]:
    if only_archived:
        archive_clause = " AND archived = 1"
    elif include_archived:
        archive_clause = ""
    else:
        archive_clause = " AND archived = 0"
    rows = conn.execute(
        f"SELECT * FROM tags WHERE workspace_id = ?{archive_clause} ORDER BY name",
        (workspace_id,),
    ).fetchall()
    return tuple(row_to_tag(r) for r in rows)


def update_tag(
    conn: sqlite3.Connection,
    tag_id: int,
    changes: dict[str, Any],
) -> Tag:
    sql, params = _build_update("tags", tag_id, changes, _TAG_UPDATABLE)
    cur = conn.execute(sql, params)
    if cur.rowcount == 0:
        raise LookupError(f"tag {tag_id} not found")
    row = conn.execute("SELECT * FROM tags WHERE id = ?", (tag_id,)).fetchone()
    return row_to_tag(row)


# ---- Task-tag join table functions ----


def add_tag_to_task(
    conn: sqlite3.Connection,
    task_id: int,
    tag_id: int,
) -> None:
    conn.execute(
        "INSERT INTO task_tags (task_id, tag_id, workspace_id) "
        "VALUES (?, ?, (SELECT workspace_id FROM tasks WHERE id = ?))",
        (task_id, tag_id, task_id),
    )


def remove_tag_from_task(
    conn: sqlite3.Connection,
    task_id: int,
    tag_id: int,
) -> None:
    conn.execute(
        "DELETE FROM task_tags WHERE task_id = ? AND tag_id = ?",
        (task_id, tag_id),
    )


def remove_all_task_tags_by_tag(conn: sqlite3.Connection, tag_id: int) -> None:
    """Remove all task assignments for a tag (used before archiving)."""
    conn.execute("DELETE FROM task_tags WHERE tag_id = ?", (tag_id,))


def list_tag_ids_by_task(
    conn: sqlite3.Connection,
    task_id: int,
    *,
    include_archived: bool = False,
) -> tuple[int, ...]:
    archive_clause = (
        "" if include_archived else " JOIN tags t ON t.id = tt.tag_id AND t.archived = 0"
    )
    rows = conn.execute(
        f"SELECT tt.tag_id FROM task_tags tt{archive_clause} WHERE tt.task_id = ?",
        (task_id,),
    ).fetchall()
    return tuple(r["tag_id"] for r in rows)


def list_tags_by_task(
    conn: sqlite3.Connection,
    task_id: int,
    *,
    include_archived: bool = False,
) -> tuple[Tag, ...]:
    archive_clause = "" if include_archived else " AND t.archived = 0"
    rows = conn.execute(
        f"SELECT t.* FROM tags t "
        f"JOIN task_tags tt ON t.id = tt.tag_id "
        f"WHERE tt.task_id = ?{archive_clause} ORDER BY t.name",
        (task_id,),
    ).fetchall()
    return tuple(row_to_tag(r) for r in rows)


def list_task_ids_by_tag(
    conn: sqlite3.Connection,
    tag_id: int,
) -> tuple[int, ...]:
    rows = conn.execute(
        "SELECT task_id FROM task_tags WHERE tag_id = ?",
        (tag_id,),
    ).fetchall()
    return tuple(r["task_id"] for r in rows)


def batch_tag_ids_by_task(
    conn: sqlite3.Connection,
    task_ids: tuple[int, ...],
    *,
    include_archived: bool = False,
) -> dict[int, tuple[int, ...]]:
    """Return {task_id: tuple_of_tag_ids} for a batch of task IDs."""
    if not task_ids:
        return {}
    placeholders = ",".join("?" * len(task_ids))
    archive_clause = "" if include_archived else " AND t.archived = 0"
    rows = conn.execute(
        f"SELECT tt.task_id, tt.tag_id FROM task_tags tt "
        f"JOIN tags t ON t.id = tt.tag_id "
        f"WHERE tt.task_id IN ({placeholders}){archive_clause}",
        task_ids,
    ).fetchall()
    intermediate: dict[int, list[int]] = {}
    for r in rows:
        intermediate.setdefault(r["task_id"], []).append(r["tag_id"])
    return {tid: tuple(intermediate.get(tid, ())) for tid in task_ids}


# ---- Group functions ----


def insert_group(conn: sqlite3.Connection, new: NewGroup) -> Group:
    d = _asdict_for_insert(new)
    cur = conn.execute(
        "INSERT INTO groups (workspace_id, title, description, parent_id, position) "
        "VALUES (:workspace_id, :title, :description, :parent_id, :position)",
        d,
    )
    row = conn.execute("SELECT * FROM groups WHERE id = ?", (cur.lastrowid,)).fetchone()
    return row_to_group(row)


def get_group(conn: sqlite3.Connection, group_id: int) -> Group | None:
    row = conn.execute("SELECT * FROM groups WHERE id = ?", (group_id,)).fetchone()
    return row_to_group(row) if row else None


def get_group_by_title(
    conn: sqlite3.Connection,
    workspace_id: int,
    parent_id: int | None,
    title: str,
) -> Group | None:
    if parent_id is None:
        row = conn.execute(
            "SELECT * FROM groups WHERE workspace_id = ? AND parent_id IS NULL "
            "AND title = ? AND archived = 0",
            (workspace_id, title),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT * FROM groups WHERE workspace_id = ? AND parent_id = ? "
            "AND title = ? AND archived = 0",
            (workspace_id, parent_id, title),
        ).fetchone()
    return row_to_group(row) if row else None


def list_groups(
    conn: sqlite3.Connection,
    workspace_id: int,
    *,
    parent_id: int | None = None,
    include_archived: bool = False,
    only_archived: bool = False,
) -> tuple[Group, ...]:
    if only_archived:
        archive_clause = " AND archived = 1"
    elif include_archived:
        archive_clause = ""
    else:
        archive_clause = " AND archived = 0"
    if parent_id is None:
        rows = conn.execute(
            f"SELECT * FROM groups WHERE workspace_id = ? AND parent_id IS NULL"
            f"{archive_clause} ORDER BY position, id",
            (workspace_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            f"SELECT * FROM groups WHERE workspace_id = ? AND parent_id = ?"
            f"{archive_clause} ORDER BY position, id",
            (workspace_id, parent_id),
        ).fetchall()
    return tuple(row_to_group(r) for r in rows)


def list_root_groups(
    conn: sqlite3.Connection,
    workspace_id: int,
    *,
    include_archived: bool = False,
) -> tuple[Group, ...]:
    return list_groups(
        conn, workspace_id, parent_id=None, include_archived=include_archived
    )


def update_group(
    conn: sqlite3.Connection,
    group_id: int,
    changes: dict[str, Any],
) -> Group:
    sql, params = _build_update("groups", group_id, changes, _GROUP_UPDATABLE)
    cur = conn.execute(sql, params)
    if cur.rowcount == 0:
        raise LookupError(f"group {group_id} not found")
    row = conn.execute("SELECT * FROM groups WHERE id = ?", (group_id,)).fetchone()
    return row_to_group(row)


# ---- Task-group functions ----


def set_task_group_id(
    conn: sqlite3.Connection,
    task_id: int,
    group_id: int | None,
) -> None:
    cur = conn.execute("UPDATE tasks SET group_id = ? WHERE id = ?", (group_id, task_id))
    if cur.rowcount == 0:
        raise LookupError(f"task {task_id} not found")


def unassign_tasks_from_group(
    conn: sqlite3.Connection,
    group_id: int,
) -> None:
    conn.execute("UPDATE tasks SET group_id = NULL WHERE group_id = ?", (group_id,))


def list_task_ids_by_group(
    conn: sqlite3.Connection,
    group_id: int,
    *,
    include_archived: bool = False,
) -> tuple[int, ...]:
    archive_clause = "" if include_archived else " AND archived = 0"
    rows = conn.execute(
        f"SELECT id FROM tasks WHERE group_id = ?{archive_clause}", (group_id,)
    ).fetchall()
    return tuple(r["id"] for r in rows)


def batch_task_ids_by_group(
    conn: sqlite3.Connection,
    group_ids: tuple[int, ...],
    *,
    include_archived: bool = False,
) -> dict[int, tuple[int, ...]]:
    """Return {group_id: (task_id, ...)} for a batch of group IDs."""
    if not group_ids:
        return {}
    placeholders = ",".join("?" * len(group_ids))
    archive_clause = "" if include_archived else " AND archived = 0"
    rows = conn.execute(
        f"SELECT group_id, id FROM tasks WHERE group_id IN ({placeholders}){archive_clause}",
        group_ids,
    ).fetchall()
    mapping: dict[int, list[int]] = {}
    for r in rows:
        mapping.setdefault(r["group_id"], []).append(r["id"])
    return {gid: tuple(mapping.get(gid, ())) for gid in group_ids}


def batch_child_ids_by_group(
    conn: sqlite3.Connection,
    group_ids: tuple[int, ...],
    *,
    include_archived: bool = False,
) -> dict[int, tuple[int, ...]]:
    """Return {parent_group_id: (child_group_id, ...)} for a batch of group IDs."""
    if not group_ids:
        return {}
    placeholders = ",".join("?" * len(group_ids))
    archive_clause = "" if include_archived else " AND archived = 0"
    rows = conn.execute(
        f"SELECT id, parent_id FROM groups "
        f"WHERE parent_id IN ({placeholders}){archive_clause} "
        f"ORDER BY position, id",
        group_ids,
    ).fetchall()
    mapping: dict[int, list[int]] = {}
    for r in rows:
        mapping.setdefault(r["parent_id"], []).append(r["id"])
    return {gid: tuple(mapping.get(gid, ())) for gid in group_ids}


def list_groups_by_workspace(
    conn: sqlite3.Connection,
    workspace_id: int,
    *,
    include_archived: bool = False,
    title: str | None = None,
) -> tuple[Group, ...]:
    """Return all groups on a workspace, ordered by position.

    If *title* is given, only groups whose title matches are returned.
    The match is case-insensitive because the groups.title column has
    COLLATE NOCASE in the schema.
    """
    archive_clause = "" if include_archived else " AND archived = 0"
    title_clause = " AND title = ?" if title is not None else ""
    params: list[object] = [workspace_id]
    if title is not None:
        params.append(title)
    rows = conn.execute(
        f"SELECT * FROM groups "
        f"WHERE workspace_id = ?{archive_clause}{title_clause} "
        "ORDER BY position, id",
        params,
    ).fetchall()
    return tuple(row_to_group(r) for r in rows)


def list_ungrouped_task_ids(
    conn: sqlite3.Connection,
    workspace_id: int,
) -> tuple[int, ...]:
    rows = conn.execute(
        "SELECT id FROM tasks WHERE workspace_id = ? AND archived = 0 AND group_id IS NULL",
        (workspace_id,),
    ).fetchall()
    return tuple(r["id"] for r in rows)


# ---- Group tree operations ----


def list_child_groups(
    conn: sqlite3.Connection,
    group_id: int,
    *,
    include_archived: bool = False,
) -> tuple[Group, ...]:
    archive_clause = "" if include_archived else " AND archived = 0"
    rows = conn.execute(
        f"SELECT * FROM groups WHERE parent_id = ?{archive_clause} ORDER BY position, id",
        (group_id,),
    ).fetchall()
    return tuple(row_to_group(r) for r in rows)


def get_subtree_group_ids(
    conn: sqlite3.Connection,
    group_id: int,
) -> tuple[int, ...]:
    rows = conn.execute(
        "WITH RECURSIVE subtree AS ("
        "  SELECT id FROM groups WHERE id = ? "
        "  UNION ALL "
        "  SELECT g.id FROM groups g "
        "  JOIN subtree s ON g.parent_id = s.id"
        ") SELECT id FROM subtree",
        (group_id,),
    ).fetchall()
    return tuple(r["id"] for r in rows)


def get_group_ancestry(
    conn: sqlite3.Connection,
    group_id: int,
) -> tuple[Group, ...]:
    """Return groups from root to the given group, inclusive."""
    rows = conn.execute(
        "WITH RECURSIVE ancestry AS ("
        "  SELECT id, workspace_id, title, description, metadata, parent_id, position, archived, created_at, 0 AS depth "
        "  FROM groups WHERE id = ? "
        "  UNION ALL "
        "  SELECT g.id, g.workspace_id, g.title, g.description, g.metadata, g.parent_id, g.position, g.archived, g.created_at, a.depth + 1 "
        "  FROM groups g JOIN ancestry a ON g.id = a.parent_id"
        ") SELECT id, workspace_id, title, description, metadata, parent_id, position, archived, created_at "
        "FROM ancestry ORDER BY depth DESC",
        (group_id,),
    ).fetchall()
    return tuple(row_to_group(r) for r in rows)


def reparent_children(
    conn: sqlite3.Connection,
    group_id: int,
    new_parent_id: int | None,
) -> None:
    conn.execute(
        "UPDATE groups SET parent_id = ? WHERE parent_id = ?",
        (new_parent_id, group_id),
    )


# ---- Archive count queries (read-only, for dry-run) ----


# Intentionally traverses all children including archived ones. This is
# defensive: if a non-archived child somehow exists under an archived
# intermediate group (data inconsistency), the CTE still finds it.  The
# caller's leaf query filters on `archived = 0` as needed.
_SUBTREE_CTE = (
    "WITH RECURSIVE subtree AS ("
    "  SELECT id FROM groups WHERE id = ? "
    "  UNION ALL "
    "  SELECT g.id FROM groups g "
    "  JOIN subtree s ON g.parent_id = s.id"
    ") "
)


def count_active_tasks_in_group_subtree(
    conn: sqlite3.Connection,
    group_id: int,
) -> int:
    row = conn.execute(
        _SUBTREE_CTE + "SELECT COUNT(*) AS cnt FROM tasks "
        "WHERE group_id IN (SELECT id FROM subtree) AND archived = 0",
        (group_id,),
    ).fetchone()
    return row["cnt"]


def count_active_descendant_groups(
    conn: sqlite3.Connection,
    group_id: int,
) -> int:
    row = conn.execute(
        _SUBTREE_CTE + "SELECT COUNT(*) AS cnt FROM subtree "
        "JOIN groups g ON subtree.id = g.id "
        "WHERE g.archived = 0 AND g.id != ?",
        (group_id, group_id),
    ).fetchone()
    return row["cnt"]


def count_active_tasks_in_workspace(
    conn: sqlite3.Connection,
    workspace_id: int,
) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS cnt FROM tasks WHERE workspace_id = ? AND archived = 0",
        (workspace_id,),
    ).fetchone()
    return row["cnt"]


def count_active_groups_in_workspace(
    conn: sqlite3.Connection,
    workspace_id: int,
) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS cnt FROM groups WHERE workspace_id = ? AND archived = 0",
        (workspace_id,),
    ).fetchone()
    return row["cnt"]


def count_active_statuses_in_workspace(
    conn: sqlite3.Connection,
    workspace_id: int,
) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS cnt FROM statuses WHERE workspace_id = ? AND archived = 0",
        (workspace_id,),
    ).fetchone()
    return row["cnt"]


def count_active_tasks_by_status(
    conn: sqlite3.Connection,
    status_id: int,
) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS cnt FROM tasks WHERE status_id = ? AND archived = 0",
        (status_id,),
    ).fetchone()
    return row["cnt"]


def count_active_tasks_by_tag(
    conn: sqlite3.Connection,
    tag_id: int,
) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS cnt FROM task_tags tt "
        "JOIN tasks t ON tt.task_id = t.id "
        "WHERE tt.tag_id = ? AND t.archived = 0",
        (tag_id,),
    ).fetchone()
    return row["cnt"]


# ---- Active task-ID lists (for history recording before bulk archive) ----


def list_active_task_ids_in_group_subtree(
    conn: sqlite3.Connection,
    group_id: int,
) -> tuple[int, ...]:
    rows = conn.execute(
        _SUBTREE_CTE + "SELECT id FROM tasks "
        "WHERE group_id IN (SELECT id FROM subtree) AND archived = 0",
        (group_id,),
    ).fetchall()
    return tuple(r["id"] for r in rows)


def list_active_task_ids_in_workspace(
    conn: sqlite3.Connection,
    workspace_id: int,
) -> tuple[int, ...]:
    rows = conn.execute(
        "SELECT id FROM tasks WHERE workspace_id = ? AND archived = 0",
        (workspace_id,),
    ).fetchall()
    return tuple(r["id"] for r in rows)


# ---- Bulk-archive mutations ----


def archive_tasks_in_group_subtree(
    conn: sqlite3.Connection,
    group_id: int,
) -> int:
    cur = conn.execute(
        _SUBTREE_CTE + "UPDATE tasks SET archived = 1 "
        "WHERE group_id IN (SELECT id FROM subtree) AND archived = 0",
        (group_id,),
    )
    return cur.rowcount


def archive_descendant_groups(
    conn: sqlite3.Connection,
    group_id: int,
) -> int:
    cur = conn.execute(
        _SUBTREE_CTE + "UPDATE groups SET archived = 1 "
        "WHERE id IN (SELECT id FROM subtree) AND id != ? AND archived = 0",
        (group_id, group_id),
    )
    return cur.rowcount


def archive_tasks_in_workspace(
    conn: sqlite3.Connection,
    workspace_id: int,
) -> int:
    cur = conn.execute(
        "UPDATE tasks SET archived = 1 WHERE workspace_id = ? AND archived = 0",
        (workspace_id,),
    )
    return cur.rowcount


def archive_groups_in_workspace(
    conn: sqlite3.Connection,
    workspace_id: int,
) -> int:
    cur = conn.execute(
        "UPDATE groups SET archived = 1 WHERE workspace_id = ? AND archived = 0",
        (workspace_id,),
    )
    return cur.rowcount


def archive_statuses_in_workspace(
    conn: sqlite3.Connection,
    workspace_id: int,
) -> int:
    cur = conn.execute(
        "UPDATE statuses SET archived = 1 WHERE workspace_id = ? AND archived = 0",
        (workspace_id,),
    )
    return cur.rowcount


