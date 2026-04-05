from __future__ import annotations

import dataclasses
import re
import sqlite3
from typing import Any

from .mappers import (
    row_to_board,
    row_to_column,
    row_to_group,
    row_to_project,
    row_to_tag,
    row_to_task,
    row_to_task_history,
)
from .models import (
    Board,
    Column,
    Group,
    NewBoard,
    NewColumn,
    NewGroup,
    NewProject,
    NewTag,
    NewTask,
    NewTaskHistory,
    Project,
    Tag,
    Task,
    TaskFilter,
    TaskHistory,
)

# ---- Updatable-field allowlists ----

_BOARD_UPDATABLE: frozenset[str] = frozenset({"name", "archived"})
_COLUMN_UPDATABLE: frozenset[str] = frozenset({"name", "position", "archived"})
_PROJECT_UPDATABLE: frozenset[str] = frozenset({"name", "description", "archived"})
# group_id is intentionally excluded — assignment goes through
# set_task_group_id / assign_task_to_group which enforce project-matching
# invariants and record history that update_task would skip.
_TASK_UPDATABLE: frozenset[str] = frozenset({
    "title",
    "description",
    "column_id",
    "project_id",
    "priority",
    "due_date",
    "position",
    "archived",
    "start_date",
    "finish_date",
})
_TAG_UPDATABLE: frozenset[str] = frozenset({"name", "archived"})
_GROUP_UPDATABLE: frozenset[str] = frozenset({
    "title", "parent_id", "position", "archived",
})


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


# ---- Board functions ----


def insert_board(conn: sqlite3.Connection, new: NewBoard) -> Board:
    d = _asdict_for_insert(new)
    cur = conn.execute("INSERT INTO boards (name) VALUES (:name)", d)
    row = conn.execute("SELECT * FROM boards WHERE id = ?", (cur.lastrowid,)).fetchone()
    return row_to_board(row)


def get_board(conn: sqlite3.Connection, board_id: int) -> Board | None:
    row = conn.execute("SELECT * FROM boards WHERE id = ?", (board_id,)).fetchone()
    return row_to_board(row) if row else None


def get_board_by_name(conn: sqlite3.Connection, name: str) -> Board | None:
    row = conn.execute(
        "SELECT * FROM boards WHERE name = ? AND archived = 0", (name,)
    ).fetchone()
    return row_to_board(row) if row else None


def list_boards(
    conn: sqlite3.Connection,
    *,
    include_archived: bool = False,
) -> tuple[Board, ...]:
    archive_clause = "" if include_archived else " WHERE archived = 0"
    rows = conn.execute(
        f"SELECT * FROM boards{archive_clause} ORDER BY created_at"
    ).fetchall()
    return tuple(row_to_board(r) for r in rows)


def update_board(
    conn: sqlite3.Connection,
    board_id: int,
    changes: dict[str, Any],
) -> Board:
    sql, params = _build_update("boards", board_id, changes, _BOARD_UPDATABLE)
    cur = conn.execute(sql, params)
    if cur.rowcount == 0:
        raise LookupError(f"board {board_id} not found")
    row = conn.execute("SELECT * FROM boards WHERE id = ?", (board_id,)).fetchone()
    return row_to_board(row)


# ---- Column functions ----


def insert_column(conn: sqlite3.Connection, new: NewColumn) -> Column:
    d = _asdict_for_insert(new)
    cur = conn.execute(
        "INSERT INTO columns (board_id, name, position) VALUES (:board_id, :name, :position)",
        d,
    )
    row = conn.execute("SELECT * FROM columns WHERE id = ?", (cur.lastrowid,)).fetchone()
    return row_to_column(row)


def get_column_by_name(
    conn: sqlite3.Connection,
    board_id: int,
    name: str,
) -> Column | None:
    row = conn.execute(
        "SELECT * FROM columns WHERE board_id = ? AND name = ? AND archived = 0",
        (board_id, name),
    ).fetchone()
    return row_to_column(row) if row else None


def get_column(conn: sqlite3.Connection, column_id: int) -> Column | None:
    row = conn.execute("SELECT * FROM columns WHERE id = ?", (column_id,)).fetchone()
    return row_to_column(row) if row else None


def list_columns(
    conn: sqlite3.Connection,
    board_id: int,
    *,
    include_archived: bool = False,
) -> tuple[Column, ...]:
    archive_clause = "" if include_archived else " AND archived = 0"
    rows = conn.execute(
        f"SELECT * FROM columns WHERE board_id = ?{archive_clause} ORDER BY position, id",
        (board_id,),
    ).fetchall()
    return tuple(row_to_column(r) for r in rows)


def update_column(
    conn: sqlite3.Connection,
    column_id: int,
    changes: dict[str, Any],
) -> Column:
    sql, params = _build_update("columns", column_id, changes, _COLUMN_UPDATABLE)
    cur = conn.execute(sql, params)
    if cur.rowcount == 0:
        raise LookupError(f"column {column_id} not found")
    row = conn.execute("SELECT * FROM columns WHERE id = ?", (column_id,)).fetchone()
    return row_to_column(row)


# ---- Project functions ----


def insert_project(conn: sqlite3.Connection, new: NewProject) -> Project:
    d = _asdict_for_insert(new)
    cur = conn.execute(
        "INSERT INTO projects (board_id, name, description) "
        "VALUES (:board_id, :name, :description)",
        d,
    )
    row = conn.execute("SELECT * FROM projects WHERE id = ?", (cur.lastrowid,)).fetchone()
    return row_to_project(row)


def get_project_by_name(
    conn: sqlite3.Connection,
    board_id: int,
    name: str,
) -> Project | None:
    row = conn.execute(
        "SELECT * FROM projects WHERE board_id = ? AND name = ? AND archived = 0",
        (board_id, name),
    ).fetchone()
    return row_to_project(row) if row else None


def get_project(conn: sqlite3.Connection, project_id: int) -> Project | None:
    row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    return row_to_project(row) if row else None


def list_projects(
    conn: sqlite3.Connection,
    board_id: int,
    *,
    include_archived: bool = False,
) -> tuple[Project, ...]:
    archive_clause = "" if include_archived else " AND archived = 0"
    rows = conn.execute(
        f"SELECT * FROM projects WHERE board_id = ?{archive_clause} ORDER BY created_at",
        (board_id,),
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
        "(board_id, title, column_id, project_id, description, priority, due_date, position, start_date, finish_date) "
        "VALUES (:board_id, :title, :column_id, :project_id, :description, :priority, :due_date, :position, :start_date, :finish_date)",
        d,
    )
    row = conn.execute("SELECT * FROM tasks WHERE id = ?", (cur.lastrowid,)).fetchone()
    return row_to_task(row)


def get_task(conn: sqlite3.Connection, task_id: int) -> Task | None:
    row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    return row_to_task(row) if row else None


def get_task_by_title(
    conn: sqlite3.Connection,
    board_id: int,
    title: str,
) -> Task | None:
    row = conn.execute(
        "SELECT * FROM tasks WHERE board_id = ? AND title = ? AND archived = 0",
        (board_id, title),
    ).fetchone()
    return row_to_task(row) if row else None


def list_tasks(
    conn: sqlite3.Connection,
    board_id: int,
    *,
    include_archived: bool = False,
) -> tuple[Task, ...]:
    archive_clause = "" if include_archived else " AND archived = 0"
    rows = conn.execute(
        f"SELECT * FROM tasks WHERE board_id = ?{archive_clause} ORDER BY position, id",
        (board_id,),
    ).fetchall()
    return tuple(row_to_task(r) for r in rows)


def list_tasks_by_column(
    conn: sqlite3.Connection,
    column_id: int,
    *,
    include_archived: bool = False,
) -> tuple[Task, ...]:
    archive_clause = "" if include_archived else " AND archived = 0"
    rows = conn.execute(
        f"SELECT * FROM tasks WHERE column_id = ?{archive_clause} ORDER BY position, id",
        (column_id,),
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
    board_id: int,
    *,
    task_filter: TaskFilter | None = None,
) -> tuple[Task, ...]:
    clauses = ["board_id = ?"]
    params: list[object] = [board_id]
    f = task_filter or TaskFilter()
    if f.only_archived:
        clauses.append("archived = 1")
    elif not f.include_archived:
        clauses.append("archived = 0")
    if f.column_id is not None:
        clauses.append("column_id = ?")
        params.append(f.column_id)
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


# ---- Task dependency functions ----


def add_dependency(
    conn: sqlite3.Connection,
    task_id: int,
    depends_on_id: int,
) -> None:
    conn.execute(
        "INSERT INTO task_dependencies (task_id, depends_on_id, board_id) "
        "VALUES (?, ?, (SELECT board_id FROM tasks WHERE id = ?))",
        (task_id, depends_on_id, task_id),
    )


def remove_dependency(
    conn: sqlite3.Connection,
    task_id: int,
    depends_on_id: int,
) -> None:
    conn.execute(
        "DELETE FROM task_dependencies WHERE task_id = ? AND depends_on_id = ?",
        (task_id, depends_on_id),
    )


def list_blocked_by_ids(
    conn: sqlite3.Connection,
    task_id: int,
) -> tuple[int, ...]:
    rows = conn.execute(
        "SELECT depends_on_id FROM task_dependencies WHERE task_id = ?",
        (task_id,),
    ).fetchall()
    return tuple(r["depends_on_id"] for r in rows)


def list_blocks_ids(
    conn: sqlite3.Connection,
    task_id: int,
) -> tuple[int, ...]:
    rows = conn.execute(
        "SELECT task_id FROM task_dependencies WHERE depends_on_id = ?",
        (task_id,),
    ).fetchall()
    return tuple(r["task_id"] for r in rows)


def batch_dependency_ids(
    conn: sqlite3.Connection,
    task_ids: tuple[int, ...],
) -> tuple[dict[int, tuple[int, ...]], dict[int, tuple[int, ...]]]:
    """Return (blocked_by_map, blocks_map) for a batch of task IDs.

    Each map is {task_id: tuple_of_related_ids}.
    """
    if not task_ids:
        return {}, {}
    placeholders = ",".join("?" * len(task_ids))
    rows = conn.execute(
        f"SELECT task_id, depends_on_id FROM task_dependencies "
        f"WHERE task_id IN ({placeholders}) OR depends_on_id IN ({placeholders})",
        (*task_ids, *task_ids),
    ).fetchall()
    blocked_by: dict[int, list[int]] = {}
    blocks: dict[int, list[int]] = {}
    for r in rows:
        tid, did = r["task_id"], r["depends_on_id"]
        blocked_by.setdefault(tid, []).append(did)
        blocks.setdefault(did, []).append(tid)
    return (
        {tid: tuple(blocked_by.get(tid, ())) for tid in task_ids},
        {tid: tuple(blocks.get(tid, ())) for tid in task_ids},
    )


def list_blocked_by_tasks(
    conn: sqlite3.Connection,
    task_id: int,
) -> tuple[Task, ...]:
    rows = conn.execute(
        "SELECT t.* FROM tasks t "
        "JOIN task_dependencies d ON t.id = d.depends_on_id "
        "WHERE d.task_id = ?",
        (task_id,),
    ).fetchall()
    return tuple(row_to_task(r) for r in rows)


def list_blocks_tasks(
    conn: sqlite3.Connection,
    task_id: int,
) -> tuple[Task, ...]:
    rows = conn.execute(
        "SELECT t.* FROM tasks t "
        "JOIN task_dependencies d ON t.id = d.task_id "
        "WHERE d.depends_on_id = ?",
        (task_id,),
    ).fetchall()
    return tuple(row_to_task(r) for r in rows)


def get_reachable_task_ids(
    conn: sqlite3.Connection,
    task_id: int,
) -> tuple[int, ...]:
    """Return all task IDs reachable from *task_id* by following depends_on edges."""
    rows = conn.execute(
        "WITH RECURSIVE reachable AS ("
        "  SELECT depends_on_id AS id FROM task_dependencies WHERE task_id = ? "
        "  UNION "
        "  SELECT td.depends_on_id FROM task_dependencies td "
        "  JOIN reachable r ON td.task_id = r.id"
        ") SELECT id FROM reachable",
        (task_id,),
    ).fetchall()
    return tuple(r["id"] for r in rows)


def list_all_dependencies(
    conn: sqlite3.Connection,
) -> tuple[tuple[int, int], ...]:
    rows = conn.execute(
        "SELECT task_id, depends_on_id FROM task_dependencies"
    ).fetchall()
    return tuple((r["task_id"], r["depends_on_id"]) for r in rows)


def list_all_task_dependencies(
    conn: sqlite3.Connection,
) -> tuple[dict, ...]:
    """Return all task_dependencies rows as plain dicts (full FK columns preserved)."""
    rows = conn.execute(
        "SELECT task_id, depends_on_id, board_id FROM task_dependencies"
    ).fetchall()
    return tuple({"task_id": r["task_id"], "depends_on_id": r["depends_on_id"], "board_id": r["board_id"]} for r in rows)


def list_all_task_tags(
    conn: sqlite3.Connection,
) -> tuple[dict, ...]:
    """Return all task_tags rows as plain dicts (full FK columns preserved)."""
    rows = conn.execute(
        "SELECT task_id, tag_id, board_id FROM task_tags"
    ).fetchall()
    return tuple({"task_id": r["task_id"], "tag_id": r["tag_id"], "board_id": r["board_id"]} for r in rows)


# ---- Task history functions ----


def insert_task_history(
    conn: sqlite3.Connection,
    new: NewTaskHistory,
) -> TaskHistory:
    d = _asdict_for_insert(new)
    cur = conn.execute(
        "INSERT INTO task_history (task_id, field, old_value, new_value, source) "
        "VALUES (:task_id, :field, :old_value, :new_value, :source)",
        d,
    )
    row = conn.execute(
        "SELECT * FROM task_history WHERE id = ?", (cur.lastrowid,)
    ).fetchone()
    return row_to_task_history(row)


def list_task_history(
    conn: sqlite3.Connection,
    task_id: int,
) -> tuple[TaskHistory, ...]:
    rows = conn.execute(
        "SELECT * FROM task_history WHERE task_id = ? ORDER BY changed_at DESC, id DESC",
        (task_id,),
    ).fetchall()
    return tuple(row_to_task_history(r) for r in rows)


def list_all_task_history(
    conn: sqlite3.Connection,
) -> tuple[TaskHistory, ...]:
    """Return all task_history rows ordered by task and time."""
    rows = conn.execute(
        "SELECT * FROM task_history ORDER BY task_id, changed_at, id"
    ).fetchall()
    return tuple(row_to_task_history(r) for r in rows)


# ---- Tag functions ----


def insert_tag(conn: sqlite3.Connection, new: NewTag) -> Tag:
    d = _asdict_for_insert(new)
    cur = conn.execute(
        "INSERT INTO tags (board_id, name) VALUES (:board_id, :name)",
        d,
    )
    row = conn.execute("SELECT * FROM tags WHERE id = ?", (cur.lastrowid,)).fetchone()
    return row_to_tag(row)


def get_tag(conn: sqlite3.Connection, tag_id: int) -> Tag | None:
    row = conn.execute("SELECT * FROM tags WHERE id = ?", (tag_id,)).fetchone()
    return row_to_tag(row) if row else None


def get_tag_by_name(
    conn: sqlite3.Connection,
    board_id: int,
    name: str,
) -> Tag | None:
    row = conn.execute(
        "SELECT * FROM tags WHERE board_id = ? AND name = ? AND archived = 0",
        (board_id, name),
    ).fetchone()
    return row_to_tag(row) if row else None


def list_tags(
    conn: sqlite3.Connection,
    board_id: int,
    *,
    include_archived: bool = False,
) -> tuple[Tag, ...]:
    archive_clause = "" if include_archived else " AND archived = 0"
    rows = conn.execute(
        f"SELECT * FROM tags WHERE board_id = ?{archive_clause} ORDER BY name",
        (board_id,),
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
        "INSERT INTO task_tags (task_id, tag_id, board_id) "
        "VALUES (?, ?, (SELECT board_id FROM tasks WHERE id = ?))",
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
    archive_clause = "" if include_archived else " JOIN tags t ON t.id = tt.tag_id AND t.archived = 0"
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
        "INSERT INTO groups (project_id, title, parent_id, position) "
        "VALUES (:project_id, :title, :parent_id, :position)",
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
) -> tuple[Group, ...]:
    archive_clause = "" if include_archived else " AND archived = 0"
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


def list_groups_by_board(
    conn: sqlite3.Connection,
    board_id: int,
    *,
    include_archived: bool = False,
    title: str | None = None,
) -> tuple[Group, ...]:
    """Return all groups for projects on a board, ordered by position.

    If *title* is given, only groups whose title matches are returned.
    The match is case-insensitive because the groups.title column has
    COLLATE NOCASE in the schema.
    """
    archive_clause = "" if include_archived else " AND g.archived = 0"
    title_clause = " AND g.title = ?" if title is not None else ""
    params: list[object] = [board_id]
    if title is not None:
        params.append(title)
    rows = conn.execute(
        "SELECT g.* FROM groups g "
        "JOIN projects p ON g.project_id = p.id "
        f"WHERE p.board_id = ?{archive_clause}{title_clause} "
        "ORDER BY g.position, g.id",
        params,
    ).fetchall()
    return tuple(row_to_group(r) for r in rows)


def list_ungrouped_task_ids(
    conn: sqlite3.Connection,
    project_id: int,
) -> tuple[int, ...]:
    rows = conn.execute(
        "SELECT id FROM tasks "
        "WHERE project_id = ? AND archived = 0 AND group_id IS NULL",
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
        "  SELECT id, project_id, title, parent_id, position, archived, created_at, 0 AS depth "
        "  FROM groups WHERE id = ? "
        "  UNION ALL "
        "  SELECT g.id, g.project_id, g.title, g.parent_id, g.position, g.archived, g.created_at, a.depth + 1 "
        "  FROM groups g JOIN ancestry a ON g.id = a.parent_id"
        ") SELECT id, project_id, title, parent_id, position, archived, created_at "
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


