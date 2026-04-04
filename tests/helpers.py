"""Shared factory helpers for tests. Return lastrowid, never hardcode IDs."""

from __future__ import annotations

import sqlite3


def insert_board(
    conn: sqlite3.Connection,
    name: str = "board1",
) -> int:
    cur = conn.execute("INSERT INTO boards (name) VALUES (?)", (name,))
    return cur.lastrowid  # type: ignore[return-value]


def insert_column(
    conn: sqlite3.Connection,
    board_id: int,
    name: str = "todo",
    position: int = 0,
) -> int:
    cur = conn.execute(
        "INSERT INTO columns (board_id, name, position) VALUES (?, ?, ?)",
        (board_id, name, position),
    )
    return cur.lastrowid  # type: ignore[return-value]


def insert_project(
    conn: sqlite3.Connection,
    board_id: int,
    name: str = "proj1",
    description: str | None = "desc",
) -> int:
    cur = conn.execute(
        "INSERT INTO projects (board_id, name, description) VALUES (?, ?, ?)",
        (board_id, name, description),
    )
    return cur.lastrowid  # type: ignore[return-value]


def insert_task(
    conn: sqlite3.Connection,
    board_id: int,
    title: str,
    column_id: int,
    project_id: int | None = None,
    priority: int = 1,
    due_date: int | None = None,
) -> int:
    cur = conn.execute(
        "INSERT INTO tasks (board_id, title, column_id, project_id, priority, due_date) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (board_id, title, column_id, project_id, priority, due_date),
    )
    return cur.lastrowid  # type: ignore[return-value]


def insert_task_dependency(
    conn: sqlite3.Connection,
    task_id: int,
    depends_on_id: int,
) -> None:
    conn.execute(
        "INSERT INTO task_dependencies (task_id, depends_on_id, board_id) "
        "VALUES (?, ?, (SELECT board_id FROM tasks WHERE id = ?))",
        (task_id, depends_on_id, task_id),
    )


def insert_group(
    conn: sqlite3.Connection,
    project_id: int,
    title: str = "group1",
    parent_id: int | None = None,
    position: int = 0,
) -> int:
    cur = conn.execute(
        "INSERT INTO groups (project_id, title, parent_id, position) VALUES (?, ?, ?, ?)",
        (project_id, title, parent_id, position),
    )
    return cur.lastrowid  # type: ignore[return-value]


def insert_tag(
    conn: sqlite3.Connection,
    board_id: int,
    name: str = "tag1",
) -> int:
    cur = conn.execute(
        "INSERT INTO tags (board_id, name) VALUES (?, ?)",
        (board_id, name),
    )
    return cur.lastrowid  # type: ignore[return-value]


def insert_task_tag(
    conn: sqlite3.Connection,
    task_id: int,
    tag_id: int,
) -> None:
    conn.execute(
        "INSERT INTO task_tags (task_id, tag_id, board_id) "
        "VALUES (?, ?, (SELECT board_id FROM tasks WHERE id = ?))",
        (task_id, tag_id, task_id),
    )


def insert_task_history(
    conn: sqlite3.Connection,
    task_id: int,
    field: str = "title",
    old_value: str | None = "old",
    new_value: str | None = "new",
    source: str = "tui",
) -> int:
    cur = conn.execute(
        "INSERT INTO task_history (task_id, field, old_value, new_value, source) "
        "VALUES (?, ?, ?, ?, ?)",
        (task_id, field, old_value, new_value, source),
    )
    return cur.lastrowid  # type: ignore[return-value]
