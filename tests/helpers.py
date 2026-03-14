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
) -> int:
    cur = conn.execute(
        "INSERT INTO tasks (board_id, title, column_id, project_id, priority) "
        "VALUES (?, ?, ?, ?, ?)",
        (board_id, title, column_id, project_id, priority),
    )
    return cur.lastrowid  # type: ignore[return-value]


def insert_task_dependency(
    conn: sqlite3.Connection,
    task_id: int,
    depends_on_id: int,
) -> None:
    conn.execute(
        "INSERT INTO task_dependencies (task_id, depends_on_id) VALUES (?, ?)",
        (task_id, depends_on_id),
    )


def insert_task_history(
    conn: sqlite3.Connection,
    task_id: int,
    field: str = "title",
    old_value: str | None = "old",
    new_value: str = "new",
    source: str = "tui",
) -> int:
    cur = conn.execute(
        "INSERT INTO task_history (task_id, field, old_value, new_value, source) "
        "VALUES (?, ?, ?, ?, ?)",
        (task_id, field, old_value, new_value, source),
    )
    return cur.lastrowid  # type: ignore[return-value]
