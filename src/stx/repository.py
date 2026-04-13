from __future__ import annotations

import dataclasses
import json
import re
import sqlite3
from typing import Any

from .mappers import (
    row_to_group,
    row_to_group_edge_list_item,
    row_to_journal_entry,
    row_to_project,
    row_to_status,
    row_to_tag,
    row_to_task,
    row_to_task_edge_list_item,
    row_to_workspace,
)
from .models import (
    EntityType,
    Group,
    JournalEntry,
    NewGroup,
    NewJournalEntry,
    NewProject,
    NewStatus,
    NewTag,
    NewTask,
    NewWorkspace,
    Project,
    Status,
    Tag,
    Task,
    TaskFilter,
    Workspace,
)
from .service_models import GroupEdgeListItem, TaskEdgeListItem

# ---- Updatable-field allowlists ----

_WORKSPACE_UPDATABLE: frozenset[str] = frozenset({"name", "archived"})
_STATUS_UPDATABLE: frozenset[str] = frozenset({"name", "archived"})
_PROJECT_UPDATABLE: frozenset[str] = frozenset({"name", "description", "archived"})
_TASK_UPDATABLE: frozenset[str] = frozenset(
    {
        "title",
        "description",
        "status_id",
        "project_id",
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


# ---- Project functions ----


def insert_project(conn: sqlite3.Connection, new: NewProject) -> Project:
    d = _asdict_for_insert(new)
    cur = conn.execute(
        "INSERT INTO projects (workspace_id, name, description) "
        "VALUES (:workspace_id, :name, :description)",
        d,
    )
    row = conn.execute("SELECT * FROM projects WHERE id = ?", (cur.lastrowid,)).fetchone()
    return row_to_project(row)


def get_project_by_name(
    conn: sqlite3.Connection,
    workspace_id: int,
    name: str,
) -> Project | None:
    row = conn.execute(
        "SELECT * FROM projects WHERE workspace_id = ? AND name = ? AND archived = 0",
        (workspace_id, name),
    ).fetchone()
    return row_to_project(row) if row else None


def get_project(conn: sqlite3.Connection, project_id: int) -> Project | None:
    row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    return row_to_project(row) if row else None


def list_projects(
    conn: sqlite3.Connection,
    workspace_id: int,
    *,
    include_archived: bool = False,
    only_archived: bool = False,
) -> tuple[Project, ...]:
    if only_archived:
        archive_clause = " AND archived = 1"
    elif include_archived:
        archive_clause = ""
    else:
        archive_clause = " AND archived = 0"
    rows = conn.execute(
        f"SELECT * FROM projects WHERE workspace_id = ?{archive_clause} ORDER BY created_at",
        (workspace_id,),
    ).fetchall()
    return tuple(row_to_project(r) for r in rows)


def update_project(
    conn: sqlite3.Connection,
    project_id: int,
    changes: dict[str, Any],
) -> Project:
    sql, params = _build_update("projects", project_id, changes, _PROJECT_UPDATABLE)
    cur = conn.execute(sql, params)
    if cur.rowcount == 0:
        raise LookupError(f"project {project_id} not found")
    row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    return row_to_project(row)


# ---- Task functions ----


def insert_task(conn: sqlite3.Connection, new: NewTask) -> Task:
    d = _asdict_for_insert(new)
    cur = conn.execute(
        "INSERT INTO tasks "
        "(workspace_id, title, status_id, project_id, description, priority, due_date, position, start_date, finish_date, group_id) "
        "VALUES (:workspace_id, :title, :status_id, :project_id, :description, :priority, :due_date, :position, :start_date, :finish_date, :group_id)",
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


def list_tasks_by_project(
    conn: sqlite3.Connection,
    project_id: int,
    *,
    include_archived: bool = False,
) -> tuple[Task, ...]:
    archive_clause = "" if include_archived else " AND archived = 0"
    rows = conn.execute(
        f"SELECT * FROM tasks WHERE project_id = ?{archive_clause} ORDER BY position, id",
        (project_id,),
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
    if f.project_id is not None:
        clauses.append("project_id = ?")
        params.append(f.project_id)
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
    "projects": "project",
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


def set_project_metadata_key(
    conn: sqlite3.Connection, project_id: int, key: str, value: str
) -> None:
    _set_metadata_key(conn, "projects", project_id, key, value)


def remove_project_metadata_key(conn: sqlite3.Connection, project_id: int, key: str) -> None:
    _remove_metadata_key(conn, "projects", project_id, key)


def replace_project_metadata(conn: sqlite3.Connection, project_id: int, metadata_json: str) -> None:
    _replace_metadata(conn, "projects", project_id, metadata_json)


def set_group_metadata_key(conn: sqlite3.Connection, group_id: int, key: str, value: str) -> None:
    _set_metadata_key(conn, "groups", group_id, key, value)


def remove_group_metadata_key(conn: sqlite3.Connection, group_id: int, key: str) -> None:
    _remove_metadata_key(conn, "groups", group_id, key)


def replace_group_metadata(conn: sqlite3.Connection, group_id: int, metadata_json: str) -> None:
    _replace_metadata(conn, "groups", group_id, metadata_json)


# ---- Edge metadata helpers (composite PK (source_id, target_id) — generic
#      helpers below mirror the single-id _set_metadata_key pattern. Table
#      literals are interpolated from the allowlist; callers pin the literal
#      via per-entity wrappers so user input never reaches the f-string.) ----


_EDGE_METADATA_TABLES: dict[str, str] = {
    "task_edges": "task edge",
    "group_edges": "group edge",
}


def _check_edge_table(table: str) -> None:
    if table not in _EDGE_METADATA_TABLES:
        raise ValueError(f"invalid edge metadata table: {table!r}")


def _get_edge_metadata(
    conn: sqlite3.Connection, table: str, source_id: int, target_id: int
) -> dict[str, str]:
    _check_edge_table(table)
    row = conn.execute(
        f"SELECT metadata FROM {table} "
        f"WHERE source_id = ? AND target_id = ? AND archived = 0",
        (source_id, target_id),
    ).fetchone()
    if row is None:
        raise LookupError(f"{_EDGE_METADATA_TABLES[table]} ({source_id}, {target_id}) not found")
    return json.loads(row["metadata"])


def _get_edge_workspace_id(
    conn: sqlite3.Connection, table: str, source_id: int, target_id: int
) -> int:
    _check_edge_table(table)
    row = conn.execute(
        f"SELECT workspace_id FROM {table} "
        f"WHERE source_id = ? AND target_id = ? AND archived = 0",
        (source_id, target_id),
    ).fetchone()
    if row is None:
        raise LookupError(f"{_EDGE_METADATA_TABLES[table]} ({source_id}, {target_id}) not found")
    return row["workspace_id"]


def _set_edge_metadata_key(
    conn: sqlite3.Connection,
    table: str,
    source_id: int,
    target_id: int,
    key: str,
    value: str,
) -> None:
    _check_edge_table(table)
    path = f'$."{key}"'
    cur = conn.execute(
        f"UPDATE {table} SET metadata = json_set(metadata, ?, ?) "
        f"WHERE source_id = ? AND target_id = ? AND archived = 0",
        (path, value, source_id, target_id),
    )
    if cur.rowcount == 0:
        raise LookupError(f"{_EDGE_METADATA_TABLES[table]} ({source_id}, {target_id}) not found")


def _remove_edge_metadata_key(
    conn: sqlite3.Connection, table: str, source_id: int, target_id: int, key: str
) -> None:
    _check_edge_table(table)
    path = f'$."{key}"'
    cur = conn.execute(
        f"UPDATE {table} SET metadata = json_remove(metadata, ?) "
        f"WHERE source_id = ? AND target_id = ? AND archived = 0",
        (path, source_id, target_id),
    )
    if cur.rowcount == 0:
        raise LookupError(f"{_EDGE_METADATA_TABLES[table]} ({source_id}, {target_id}) not found")


def _replace_edge_metadata(
    conn: sqlite3.Connection,
    table: str,
    source_id: int,
    target_id: int,
    metadata_json: str,
) -> None:
    _check_edge_table(table)
    cur = conn.execute(
        f"UPDATE {table} SET metadata = ? "
        f"WHERE source_id = ? AND target_id = ? AND archived = 0",
        (metadata_json, source_id, target_id),
    )
    if cur.rowcount == 0:
        raise LookupError(f"{_EDGE_METADATA_TABLES[table]} ({source_id}, {target_id}) not found")


# ---- Per-edge-entity public wrappers ----


def get_task_edge_metadata(
    conn: sqlite3.Connection, source_id: int, target_id: int
) -> dict[str, str]:
    return _get_edge_metadata(conn, "task_edges", source_id, target_id)


def get_task_edge_workspace_id(conn: sqlite3.Connection, source_id: int, target_id: int) -> int:
    return _get_edge_workspace_id(conn, "task_edges", source_id, target_id)


def set_task_edge_metadata_key(
    conn: sqlite3.Connection, source_id: int, target_id: int, key: str, value: str
) -> None:
    _set_edge_metadata_key(conn, "task_edges", source_id, target_id, key, value)


def remove_task_edge_metadata_key(
    conn: sqlite3.Connection, source_id: int, target_id: int, key: str
) -> None:
    _remove_edge_metadata_key(conn, "task_edges", source_id, target_id, key)


def replace_task_edge_metadata(
    conn: sqlite3.Connection, source_id: int, target_id: int, metadata_json: str
) -> None:
    _replace_edge_metadata(conn, "task_edges", source_id, target_id, metadata_json)


def get_group_edge_metadata(
    conn: sqlite3.Connection, source_id: int, target_id: int
) -> dict[str, str]:
    return _get_edge_metadata(conn, "group_edges", source_id, target_id)


def get_group_edge_workspace_id(conn: sqlite3.Connection, source_id: int, target_id: int) -> int:
    return _get_edge_workspace_id(conn, "group_edges", source_id, target_id)


def set_group_edge_metadata_key(
    conn: sqlite3.Connection, source_id: int, target_id: int, key: str, value: str
) -> None:
    _set_edge_metadata_key(conn, "group_edges", source_id, target_id, key, value)


def remove_group_edge_metadata_key(
    conn: sqlite3.Connection, source_id: int, target_id: int, key: str
) -> None:
    _remove_edge_metadata_key(conn, "group_edges", source_id, target_id, key)


def replace_group_edge_metadata(
    conn: sqlite3.Connection, source_id: int, target_id: int, metadata_json: str
) -> None:
    _replace_edge_metadata(conn, "group_edges", source_id, target_id, metadata_json)


# ---- Task edge functions ----


def add_task_edge(
    conn: sqlite3.Connection,
    source_id: int,
    target_id: int,
    workspace_id: int,
    kind: str,
) -> None:
    conn.execute(
        "INSERT INTO task_edges (source_id, target_id, workspace_id, kind) "
        "VALUES (?, ?, ?, ?) "
        "ON CONFLICT (source_id, target_id) DO UPDATE SET archived = 0, kind = excluded.kind, metadata = '{}'",
        (source_id, target_id, workspace_id, kind),
    )


def archive_task_edge(
    conn: sqlite3.Connection,
    source_id: int,
    target_id: int,
) -> None:
    conn.execute(
        "UPDATE task_edges SET archived = 1 WHERE source_id = ? AND target_id = ? AND archived = 0",
        (source_id, target_id),
    )


def list_task_edge_targets_from(
    conn: sqlite3.Connection,
    source_id: int,
) -> tuple[int, ...]:
    """Return target IDs of all active edges originating at source_id whose
    target task is also active. Archived endpoints are hidden to match the
    workspace-level `list_task_edges_by_workspace` convention."""
    rows = conn.execute(
        "SELECT e.target_id FROM task_edges e "
        "JOIN tasks t ON t.id = e.target_id "
        "WHERE e.source_id = ? AND e.archived = 0 AND t.archived = 0",
        (source_id,),
    ).fetchall()
    return tuple(r["target_id"] for r in rows)


def list_task_edge_sources_into(
    conn: sqlite3.Connection,
    target_id: int,
) -> tuple[int, ...]:
    """Return source IDs of all active edges pointing into target_id whose
    source task is also active. Archived endpoints are hidden."""
    rows = conn.execute(
        "SELECT e.source_id FROM task_edges e "
        "JOIN tasks s ON s.id = e.source_id "
        "WHERE e.target_id = ? AND e.archived = 0 AND s.archived = 0",
        (target_id,),
    ).fetchall()
    return tuple(r["source_id"] for r in rows)


def get_task_edge_kind(
    conn: sqlite3.Connection,
    source_id: int,
    target_id: int,
) -> str | None:
    """Return the kind of the active edge (source_id → target_id), or None if no active edge."""
    row = conn.execute(
        "SELECT kind FROM task_edges WHERE source_id = ? AND target_id = ? AND archived = 0",
        (source_id, target_id),
    ).fetchone()
    return row["kind"] if row is not None else None


def get_archived_task_edge_kind(
    conn: sqlite3.Connection,
    source_id: int,
    target_id: int,
) -> str | None:
    """Return the kind of an archived edge (source_id → target_id), or None if
    no archived row exists. Active rows are ignored."""
    row = conn.execute(
        "SELECT kind FROM task_edges WHERE source_id = ? AND target_id = ? AND archived = 1",
        (source_id, target_id),
    ).fetchone()
    return row["kind"] if row is not None else None


def list_task_edge_targets_from_hydrated(
    conn: sqlite3.Connection,
    source_id: int,
) -> tuple[tuple[Task, str], ...]:
    """Return (task, kind) pairs for all active targets of edges from source_id.
    Archived endpoints are hidden."""
    rows = conn.execute(
        "SELECT t.*, e.kind FROM tasks t "
        "JOIN task_edges e ON t.id = e.target_id "
        "WHERE e.source_id = ? AND e.archived = 0 AND t.archived = 0",
        (source_id,),
    ).fetchall()
    return tuple((row_to_task(r), r["kind"]) for r in rows)


def list_task_edge_sources_into_hydrated(
    conn: sqlite3.Connection,
    target_id: int,
) -> tuple[tuple[Task, str], ...]:
    """Return (task, kind) pairs for all active sources of edges pointing into target_id.
    Archived endpoints are hidden."""
    rows = conn.execute(
        "SELECT t.*, e.kind FROM tasks t "
        "JOIN task_edges e ON t.id = e.source_id "
        "WHERE e.target_id = ? AND e.archived = 0 AND t.archived = 0",
        (target_id,),
    ).fetchall()
    return tuple((row_to_task(r), r["kind"]) for r in rows)


def list_all_task_edges(
    conn: sqlite3.Connection,
) -> tuple[tuple[int, int, str], ...]:
    rows = conn.execute(
        "SELECT source_id, target_id, kind FROM task_edges WHERE archived = 0"
    ).fetchall()
    return tuple((r["source_id"], r["target_id"], r["kind"]) for r in rows)


def list_all_task_edge_rows(
    conn: sqlite3.Connection,
) -> tuple[dict, ...]:
    """Return all task_edges rows as plain dicts (full FK columns preserved)."""
    rows = conn.execute(
        "SELECT source_id, target_id, workspace_id, archived, kind, metadata FROM task_edges"
    ).fetchall()
    return tuple(
        {
            "source_id": r["source_id"],
            "target_id": r["target_id"],
            "workspace_id": r["workspace_id"],
            "archived": bool(r["archived"]),
            "kind": r["kind"],
            "metadata": json.loads(r["metadata"]),
        }
        for r in rows
    )


def list_all_group_edge_rows(
    conn: sqlite3.Connection,
) -> tuple[dict, ...]:
    """Return all group_edges rows as plain dicts (full FK columns preserved)."""
    rows = conn.execute(
        "SELECT source_id, target_id, workspace_id, archived, kind, metadata FROM group_edges"
    ).fetchall()
    return tuple(
        {
            "source_id": r["source_id"],
            "target_id": r["target_id"],
            "workspace_id": r["workspace_id"],
            "archived": bool(r["archived"]),
            "kind": r["kind"],
            "metadata": json.loads(r["metadata"]),
        }
        for r in rows
    )


def list_task_edges_by_workspace(
    conn: sqlite3.Connection,
    workspace_id: int,
    *,
    kind: str | None = None,
    task_id: int | None = None,
) -> tuple[TaskEdgeListItem, ...]:
    """Return active task edges for a workspace, optionally filtered by kind and/or task.

    Endpoint tasks are also filtered to ``archived = 0`` — archived entities
    stay hidden by default across the codebase, and edges whose endpoints
    have since been archived should not surface in active listings.
    """
    # NOTE: `clauses` must only hold statically-authored SQL fragments. All
    # user-supplied values go through `params`; never append user input to
    # the clauses list or the f-string interpolation below becomes unsafe.
    clauses = ["e.workspace_id = ?", "e.archived = 0", "s.archived = 0", "t.archived = 0"]
    params: list[Any] = [workspace_id]
    if kind is not None:
        clauses.append("e.kind = ?")
        params.append(kind)
    if task_id is not None:
        clauses.append("(e.source_id = ? OR e.target_id = ?)")
        params.extend([task_id, task_id])
    where = " AND ".join(clauses)
    rows = conn.execute(
        f"SELECT e.source_id, e.target_id, e.workspace_id, e.kind, "
        f"s.title AS source_title, t.title AS target_title "
        f"FROM task_edges e "
        f"JOIN tasks s ON s.id = e.source_id "
        f"JOIN tasks t ON t.id = e.target_id "
        f"WHERE {where} "
        f"ORDER BY e.source_id, e.target_id",
        params,
    ).fetchall()
    return tuple(row_to_task_edge_list_item(r) for r in rows)


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


# ---- Project helper ----


def list_task_ids_by_project(
    conn: sqlite3.Connection,
    project_id: int,
    *,
    include_archived: bool = False,
) -> tuple[int, ...]:
    archive_clause = "" if include_archived else " AND archived = 0"
    rows = conn.execute(
        f"SELECT id FROM tasks WHERE project_id = ?{archive_clause}",
        (project_id,),
    ).fetchall()
    return tuple(r["id"] for r in rows)


# ---- Group functions ----


def insert_group(conn: sqlite3.Connection, new: NewGroup) -> Group:
    d = _asdict_for_insert(new)
    cur = conn.execute(
        "INSERT INTO groups (workspace_id, project_id, title, description, parent_id, position) "
        "VALUES (:workspace_id, :project_id, :title, :description, :parent_id, :position)",
        d,
    )
    row = conn.execute("SELECT * FROM groups WHERE id = ?", (cur.lastrowid,)).fetchone()
    return row_to_group(row)


def get_group(conn: sqlite3.Connection, group_id: int) -> Group | None:
    row = conn.execute("SELECT * FROM groups WHERE id = ?", (group_id,)).fetchone()
    return row_to_group(row) if row else None


def get_group_by_title(
    conn: sqlite3.Connection,
    project_id: int,
    title: str,
) -> Group | None:
    row = conn.execute(
        "SELECT * FROM groups WHERE project_id = ? AND title = ? AND archived = 0",
        (project_id, title),
    ).fetchone()
    return row_to_group(row) if row else None


def list_groups(
    conn: sqlite3.Connection,
    project_id: int,
    *,
    include_archived: bool = False,
    only_archived: bool = False,
) -> tuple[Group, ...]:
    if only_archived:
        archive_clause = " AND archived = 1"
    elif include_archived:
        archive_clause = ""
    else:
        archive_clause = " AND archived = 0"
    rows = conn.execute(
        f"SELECT * FROM groups WHERE project_id = ?{archive_clause} ORDER BY position, id",
        (project_id,),
    ).fetchall()
    return tuple(row_to_group(r) for r in rows)


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
    project_id: int,
) -> tuple[int, ...]:
    rows = conn.execute(
        "SELECT id FROM tasks WHERE project_id = ? AND archived = 0 AND group_id IS NULL",
        (project_id,),
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
        "  SELECT id, workspace_id, project_id, title, description, metadata, parent_id, position, archived, created_at, 0 AS depth "
        "  FROM groups WHERE id = ? "
        "  UNION ALL "
        "  SELECT g.id, g.workspace_id, g.project_id, g.title, g.description, g.metadata, g.parent_id, g.position, g.archived, g.created_at, a.depth + 1 "
        "  FROM groups g JOIN ancestry a ON g.id = a.parent_id"
        ") SELECT id, workspace_id, project_id, title, description, metadata, parent_id, position, archived, created_at "
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


def count_active_tasks_in_project(
    conn: sqlite3.Connection,
    project_id: int,
) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS cnt FROM tasks WHERE project_id = ? AND archived = 0",
        (project_id,),
    ).fetchone()
    return row["cnt"]


def count_active_groups_in_project(
    conn: sqlite3.Connection,
    project_id: int,
) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS cnt FROM groups WHERE project_id = ? AND archived = 0",
        (project_id,),
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


def count_active_projects_in_workspace(
    conn: sqlite3.Connection,
    workspace_id: int,
) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS cnt FROM projects WHERE workspace_id = ? AND archived = 0",
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


def list_active_task_ids_in_project(
    conn: sqlite3.Connection,
    project_id: int,
) -> tuple[int, ...]:
    rows = conn.execute(
        "SELECT id FROM tasks WHERE project_id = ? AND archived = 0",
        (project_id,),
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


def archive_tasks_in_project(
    conn: sqlite3.Connection,
    project_id: int,
) -> int:
    cur = conn.execute(
        "UPDATE tasks SET archived = 1 WHERE project_id = ? AND archived = 0",
        (project_id,),
    )
    return cur.rowcount


def archive_groups_in_project(
    conn: sqlite3.Connection,
    project_id: int,
) -> int:
    cur = conn.execute(
        "UPDATE groups SET archived = 1 WHERE project_id = ? AND archived = 0",
        (project_id,),
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


def archive_projects_in_workspace(
    conn: sqlite3.Connection,
    workspace_id: int,
) -> int:
    cur = conn.execute(
        "UPDATE projects SET archived = 1 WHERE workspace_id = ? AND archived = 0",
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


# ---- Group edge functions ----


def add_group_edge(
    conn: sqlite3.Connection,
    source_id: int,
    target_id: int,
    workspace_id: int,
    kind: str,
) -> None:
    conn.execute(
        "INSERT INTO group_edges (source_id, target_id, workspace_id, kind) "
        "VALUES (?, ?, ?, ?) "
        "ON CONFLICT (source_id, target_id) DO UPDATE SET archived = 0, kind = excluded.kind, metadata = '{}'",
        (source_id, target_id, workspace_id, kind),
    )


def archive_group_edge(
    conn: sqlite3.Connection,
    source_id: int,
    target_id: int,
) -> None:
    conn.execute(
        "UPDATE group_edges SET archived = 1 WHERE source_id = ? AND target_id = ? AND archived = 0",
        (source_id, target_id),
    )


def list_group_edge_targets_from(
    conn: sqlite3.Connection,
    source_id: int,
) -> tuple[int, ...]:
    """Return target IDs of all active edges originating at source_id whose
    target group is also active. Archived endpoints are hidden."""
    rows = conn.execute(
        "SELECT e.target_id FROM group_edges e "
        "JOIN groups g ON g.id = e.target_id "
        "WHERE e.source_id = ? AND e.archived = 0 AND g.archived = 0",
        (source_id,),
    ).fetchall()
    return tuple(r["target_id"] for r in rows)


def list_all_group_edges(
    conn: sqlite3.Connection,
) -> tuple[tuple[int, int, str], ...]:
    rows = conn.execute(
        "SELECT source_id, target_id, kind FROM group_edges WHERE archived = 0"
    ).fetchall()
    return tuple((r["source_id"], r["target_id"], r["kind"]) for r in rows)


def get_group_edge_kind(
    conn: sqlite3.Connection,
    source_id: int,
    target_id: int,
) -> str | None:
    """Return the kind of the active edge (source_id → target_id), or None if no active edge."""
    row = conn.execute(
        "SELECT kind FROM group_edges WHERE source_id = ? AND target_id = ? AND archived = 0",
        (source_id, target_id),
    ).fetchone()
    return row["kind"] if row is not None else None


def get_archived_group_edge_kind(
    conn: sqlite3.Connection,
    source_id: int,
    target_id: int,
) -> str | None:
    """Return the kind of an archived edge (source_id → target_id), or None if
    no archived row exists. Active rows are ignored."""
    row = conn.execute(
        "SELECT kind FROM group_edges WHERE source_id = ? AND target_id = ? AND archived = 1",
        (source_id, target_id),
    ).fetchone()
    return row["kind"] if row is not None else None


def list_group_edge_targets_from_hydrated(
    conn: sqlite3.Connection,
    source_id: int,
) -> tuple[tuple[Group, str], ...]:
    """Return (group, kind) pairs for all active targets of edges from source_id.
    Archived endpoints are hidden."""
    rows = conn.execute(
        "SELECT g.*, e.kind FROM groups g "
        "JOIN group_edges e ON g.id = e.target_id "
        "WHERE e.source_id = ? AND e.archived = 0 AND g.archived = 0",
        (source_id,),
    ).fetchall()
    return tuple((row_to_group(r), r["kind"]) for r in rows)


def list_group_edge_sources_into_hydrated(
    conn: sqlite3.Connection,
    target_id: int,
) -> tuple[tuple[Group, str], ...]:
    """Return (group, kind) pairs for all active sources of edges pointing into target_id.
    Archived endpoints are hidden."""
    rows = conn.execute(
        "SELECT g.*, e.kind FROM groups g "
        "JOIN group_edges e ON g.id = e.source_id "
        "WHERE e.target_id = ? AND e.archived = 0 AND g.archived = 0",
        (target_id,),
    ).fetchall()
    return tuple((row_to_group(r), r["kind"]) for r in rows)


def list_group_edges_by_workspace(
    conn: sqlite3.Connection,
    workspace_id: int,
    *,
    kind: str | None = None,
    group_id: int | None = None,
) -> tuple[GroupEdgeListItem, ...]:
    """Return active group edges for a workspace, optionally filtered by kind and/or group.

    Endpoint groups are also filtered to ``archived = 0`` — same rationale
    as ``list_task_edges_by_workspace``.
    """
    # NOTE: see list_task_edges_by_workspace — `clauses` is static-only.
    clauses = ["e.workspace_id = ?", "e.archived = 0", "s.archived = 0", "t.archived = 0"]
    params: list[Any] = [workspace_id]
    if kind is not None:
        clauses.append("e.kind = ?")
        params.append(kind)
    if group_id is not None:
        clauses.append("(e.source_id = ? OR e.target_id = ?)")
        params.extend([group_id, group_id])
    where = " AND ".join(clauses)
    rows = conn.execute(
        f"SELECT e.source_id, e.target_id, e.workspace_id, e.kind, "
        f"s.title AS source_title, t.title AS target_title "
        f"FROM group_edges e "
        f"JOIN groups s ON s.id = e.source_id "
        f"JOIN groups t ON t.id = e.target_id "
        f"WHERE {where} "
        f"ORDER BY e.source_id, e.target_id",
        params,
    ).fetchall()
    return tuple(row_to_group_edge_list_item(r) for r in rows)
