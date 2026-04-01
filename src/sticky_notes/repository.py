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
    NewTask,
    NewTaskHistory,
    Project,
    Task,
    TaskFilter,
    TaskHistory,
)

# ---- Updatable-field allowlists ----

_BOARD_UPDATABLE: frozenset[str] = frozenset({"name", "archived"})
_COLUMN_UPDATABLE: frozenset[str] = frozenset({"name", "position", "archived"})
_PROJECT_UPDATABLE: frozenset[str] = frozenset({"name", "description", "archived"})
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
    row = conn.execute("SELECT * FROM boards WHERE name = ?", (name,)).fetchone()
    return row_to_board(row) if row else None


def list_boards(
    conn: sqlite3.Connection,
    *,
    include_archived: bool = False,
) -> tuple[Board, ...]:
    if include_archived:
        rows = conn.execute("SELECT * FROM boards ORDER BY created_at").fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM boards WHERE archived = 0 ORDER BY created_at"
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
        "SELECT * FROM columns WHERE board_id = ? AND name = ?",
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
    if include_archived:
        rows = conn.execute(
            "SELECT * FROM columns WHERE board_id = ? ORDER BY position",
            (board_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM columns WHERE board_id = ? AND archived = 0 ORDER BY position",
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
        "SELECT * FROM projects WHERE board_id = ? AND name = ?",
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
    if include_archived:
        rows = conn.execute(
            "SELECT * FROM projects WHERE board_id = ? ORDER BY created_at",
            (board_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM projects WHERE board_id = ? AND archived = 0 ORDER BY created_at",
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
        "SELECT * FROM tasks WHERE board_id = ? AND title = ?",
        (board_id, title),
    ).fetchone()
    return row_to_task(row) if row else None


def list_tasks(
    conn: sqlite3.Connection,
    board_id: int,
    *,
    include_archived: bool = False,
) -> tuple[Task, ...]:
    if include_archived:
        rows = conn.execute(
            "SELECT * FROM tasks WHERE board_id = ? ORDER BY position",
            (board_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM tasks WHERE board_id = ? AND archived = 0 ORDER BY position",
            (board_id,),
        ).fetchall()
    return tuple(row_to_task(r) for r in rows)


def list_tasks_by_column(
    conn: sqlite3.Connection,
    column_id: int,
    *,
    include_archived: bool = False,
) -> tuple[Task, ...]:
    if include_archived:
        rows = conn.execute(
            "SELECT * FROM tasks WHERE column_id = ? ORDER BY position",
            (column_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM tasks WHERE column_id = ? AND archived = 0 ORDER BY position",
            (column_id,),
        ).fetchall()
    return tuple(row_to_task(r) for r in rows)


def list_tasks_by_project(
    conn: sqlite3.Connection,
    project_id: int,
    *,
    include_archived: bool = False,
) -> tuple[Task, ...]:
    if include_archived:
        rows = conn.execute(
            "SELECT * FROM tasks WHERE project_id = ? ORDER BY position",
            (project_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM tasks WHERE project_id = ? AND archived = 0 ORDER BY position",
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
    if not f.include_archived:
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
    where = " AND ".join(clauses)
    rows = conn.execute(
        f"SELECT * FROM tasks WHERE {where} ORDER BY position",
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
        "INSERT INTO task_dependencies (task_id, depends_on_id) VALUES (?, ?)",
        (task_id, depends_on_id),
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


def list_all_dependencies(
    conn: sqlite3.Connection,
) -> tuple[tuple[int, int], ...]:
    rows = conn.execute(
        "SELECT task_id, depends_on_id FROM task_dependencies"
    ).fetchall()
    return tuple((r["task_id"], r["depends_on_id"]) for r in rows)


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


# ---- Project helper ----


def list_task_ids_by_project(
    conn: sqlite3.Connection,
    project_id: int,
) -> tuple[int, ...]:
    rows = conn.execute(
        "SELECT id FROM tasks WHERE project_id = ?",
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
        "SELECT * FROM groups WHERE project_id = ? AND title = ?",
        (project_id, title),
    ).fetchone()
    return row_to_group(row) if row else None


def list_groups(
    conn: sqlite3.Connection,
    project_id: int,
    *,
    include_archived: bool = False,
) -> tuple[Group, ...]:
    if include_archived:
        rows = conn.execute(
            "SELECT * FROM groups WHERE project_id = ? ORDER BY position",
            (project_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM groups WHERE project_id = ? AND archived = 0 ORDER BY position",
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


# ---- Task-group membership functions ----


def assign_task_to_group(
    conn: sqlite3.Connection,
    task_id: int,
    group_id: int,
) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO task_groups (task_id, group_id) VALUES (?, ?)",
        (task_id, group_id),
    )


def unassign_task_from_group(
    conn: sqlite3.Connection,
    task_id: int,
) -> None:
    conn.execute("DELETE FROM task_groups WHERE task_id = ?", (task_id,))


def get_task_group_id(
    conn: sqlite3.Connection,
    task_id: int,
) -> int | None:
    row = conn.execute(
        "SELECT group_id FROM task_groups WHERE task_id = ?", (task_id,)
    ).fetchone()
    return row["group_id"] if row else None


def list_task_ids_by_group(
    conn: sqlite3.Connection,
    group_id: int,
) -> tuple[int, ...]:
    rows = conn.execute(
        "SELECT task_id FROM task_groups WHERE group_id = ?", (group_id,)
    ).fetchall()
    return tuple(r["task_id"] for r in rows)


def batch_task_ids_by_group(
    conn: sqlite3.Connection,
    group_ids: tuple[int, ...],
) -> dict[int, tuple[int, ...]]:
    """Return {group_id: (task_id, ...)} for a batch of group IDs."""
    if not group_ids:
        return {}
    placeholders = ",".join("?" * len(group_ids))
    rows = conn.execute(
        f"SELECT group_id, task_id FROM task_groups "
        f"WHERE group_id IN ({placeholders})",
        group_ids,
    ).fetchall()
    mapping: dict[int, list[int]] = {}
    for r in rows:
        mapping.setdefault(r["group_id"], []).append(r["task_id"])
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
        f"ORDER BY position",
        group_ids,
    ).fetchall()
    mapping: dict[int, list[int]] = {}
    for r in rows:
        mapping.setdefault(r["parent_id"], []).append(r["id"])
    return {gid: tuple(mapping.get(gid, ())) for gid in group_ids}


def batch_group_ids_by_task(
    conn: sqlite3.Connection,
    task_ids: tuple[int, ...],
) -> dict[int, int]:
    """Return {task_id: group_id} for tasks that have a group assignment."""
    if not task_ids:
        return {}
    placeholders = ",".join("?" * len(task_ids))
    rows = conn.execute(
        f"SELECT task_id, group_id FROM task_groups "
        f"WHERE task_id IN ({placeholders})",
        task_ids,
    ).fetchall()
    return {r["task_id"]: r["group_id"] for r in rows}


def list_groups_by_board(
    conn: sqlite3.Connection,
    board_id: int,
    *,
    include_archived: bool = False,
) -> tuple[Group, ...]:
    """Return all groups for projects on a board, ordered by position."""
    archive_clause = "" if include_archived else " AND g.archived = 0"
    rows = conn.execute(
        "SELECT g.* FROM groups g "
        "JOIN projects p ON g.project_id = p.id "
        f"WHERE p.board_id = ?{archive_clause} "
        "ORDER BY g.position, g.id",
        (board_id,),
    ).fetchall()
    return tuple(row_to_group(r) for r in rows)


def list_ungrouped_task_ids(
    conn: sqlite3.Connection,
    project_id: int,
) -> tuple[int, ...]:
    rows = conn.execute(
        "SELECT t.id FROM tasks t "
        "LEFT JOIN task_groups tg ON t.id = tg.task_id "
        "WHERE t.project_id = ? AND t.archived = 0 "
        "AND tg.task_id IS NULL",
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
    if include_archived:
        rows = conn.execute(
            "SELECT * FROM groups WHERE parent_id = ? ORDER BY position",
            (group_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM groups WHERE parent_id = ? AND archived = 0 ORDER BY position",
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
        "  JOIN subtree s ON g.parent_id = s.id "
        "  WHERE g.archived = 0"
        ") SELECT id FROM subtree",
        (group_id,),
    ).fetchall()
    return tuple(r["id"] for r in rows)


def reparent_children(
    conn: sqlite3.Connection,
    group_id: int,
    new_parent_id: int | None,
) -> None:
    conn.execute(
        "UPDATE groups SET parent_id = ? WHERE parent_id = ?",
        (new_parent_id, group_id),
    )


def delete_task_groups_by_group(
    conn: sqlite3.Connection,
    group_id: int,
) -> None:
    conn.execute("DELETE FROM task_groups WHERE group_id = ?", (group_id,))
