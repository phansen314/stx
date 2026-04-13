"""Shared factory helpers for tests. Return lastrowid, never hardcode IDs."""

from __future__ import annotations

import sqlite3

from textual.app import App, ComposeResult


class ModalTestApp(App):
    """Reusable test harness: pushes a modal on mount and captures its result."""

    result: dict | None = "NOT_SET"  # type: ignore[assignment]

    def __init__(self, modal) -> None:
        super().__init__()
        self._modal = modal

    def compose(self) -> ComposeResult:
        return []

    def on_mount(self) -> None:
        self.push_screen(self._modal, callback=self._capture)

    def _capture(self, result: dict | None) -> None:
        self.result = result


def insert_workspace(
    conn: sqlite3.Connection,
    name: str = "workspace1",
) -> int:
    cur = conn.execute("INSERT INTO workspaces (name) VALUES (?)", (name,))
    return cur.lastrowid  # type: ignore[return-value]


def insert_status(
    conn: sqlite3.Connection,
    workspace_id: int,
    name: str = "todo",
) -> int:
    cur = conn.execute(
        "INSERT INTO statuses (workspace_id, name) VALUES (?, ?)",
        (workspace_id, name),
    )
    return cur.lastrowid  # type: ignore[return-value]


def insert_task(
    conn: sqlite3.Connection,
    workspace_id: int,
    title: str,
    status_id: int,
    priority: int = 1,
    due_date: int | None = None,
    description: str | None = None,
) -> int:
    cur = conn.execute(
        "INSERT INTO tasks (workspace_id, title, status_id, priority, due_date, description) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (workspace_id, title, status_id, priority, due_date, description),
    )
    return cur.lastrowid  # type: ignore[return-value]


def insert_edge(
    conn: sqlite3.Connection,
    from_type: str,
    from_id: int,
    to_type: str,
    to_id: int,
    kind: str = "blocks",
    acyclic: int = 1,
) -> None:
    """Insert a raw edge row. Uses a subquery to resolve workspace_id from the from-node."""
    if from_type == "task":
        ws_query = "SELECT workspace_id FROM tasks WHERE id = ?"
    elif from_type == "group":
        ws_query = "SELECT workspace_id FROM groups WHERE id = ?"
    elif from_type == "status":
        ws_query = "SELECT workspace_id FROM statuses WHERE id = ?"
    else:
        ws_query = "SELECT id FROM workspaces WHERE id = ?"
    conn.execute(
        f"INSERT INTO edges (from_type, from_id, to_type, to_id, workspace_id, kind, acyclic) "
        f"VALUES (?, ?, ?, ?, ({ws_query}), ?, ?)",
        (from_type, from_id, to_type, to_id, from_id, kind, acyclic),
    )


# Legacy aliases for tests that still use the old names
def insert_task_dependency(
    conn: sqlite3.Connection,
    task_id: int,
    depends_on_id: int,
    kind: str = "blocks",
) -> None:
    insert_edge(conn, "task", task_id, "task", depends_on_id, kind=kind, acyclic=1)


def insert_group_dependency(
    conn: sqlite3.Connection,
    group_id: int,
    depends_on_id: int,
    kind: str = "blocks",
) -> None:
    insert_edge(conn, "group", group_id, "group", depends_on_id, kind=kind, acyclic=1)


def insert_group(
    conn: sqlite3.Connection,
    workspace_id: int,
    title: str = "group1",
    parent_id: int | None = None,
    description: str | None = None,
) -> int:
    cur = conn.execute(
        "INSERT INTO groups (workspace_id, title, parent_id, description) "
        "VALUES (?, ?, ?, ?)",
        (workspace_id, title, parent_id, description),
    )
    return cur.lastrowid  # type: ignore[return-value]


def insert_journal_entry(
    conn: sqlite3.Connection,
    task_id: int,
    field: str = "title",
    old_value: str | None = "old",
    new_value: str | None = "new",
    source: str = "tui",
    entity_type: str = "task",
) -> int:
    cur = conn.execute(
        "INSERT INTO journal (entity_type, entity_id, workspace_id, field, old_value, new_value, source) "
        "VALUES (?, ?, (SELECT workspace_id FROM tasks WHERE id = ?), ?, ?, ?, ?)",
        (entity_type, task_id, task_id, field, old_value, new_value, source),
    )
    return cur.lastrowid  # type: ignore[return-value]
