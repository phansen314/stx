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


def insert_project(
    conn: sqlite3.Connection,
    workspace_id: int,
    name: str = "proj1",
    description: str | None = "desc",
) -> int:
    cur = conn.execute(
        "INSERT INTO projects (workspace_id, name, description) VALUES (?, ?, ?)",
        (workspace_id, name, description),
    )
    return cur.lastrowid  # type: ignore[return-value]


def insert_task(
    conn: sqlite3.Connection,
    workspace_id: int,
    title: str,
    status_id: int,
    project_id: int | None = None,
    priority: int = 1,
    due_date: int | None = None,
    description: str | None = None,
) -> int:
    cur = conn.execute(
        "INSERT INTO tasks (workspace_id, title, status_id, project_id, priority, due_date, description) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (workspace_id, title, status_id, project_id, priority, due_date, description),
    )
    return cur.lastrowid  # type: ignore[return-value]


def insert_task_dependency(
    conn: sqlite3.Connection,
    task_id: int,
    depends_on_id: int,
    kind: str = "blocks",
) -> None:
    conn.execute(
        "INSERT INTO task_edges (source_id, target_id, workspace_id, kind) "
        "VALUES (?, ?, (SELECT workspace_id FROM tasks WHERE id = ?), ?)",
        (task_id, depends_on_id, task_id, kind),
    )


def insert_group_dependency(
    conn: sqlite3.Connection,
    group_id: int,
    depends_on_id: int,
    kind: str = "blocks",
) -> None:
    conn.execute(
        "INSERT INTO group_edges (source_id, target_id, workspace_id, kind) "
        "VALUES (?, ?, (SELECT workspace_id FROM groups WHERE id = ?), ?)",
        (group_id, depends_on_id, group_id, kind),
    )


def insert_group(
    conn: sqlite3.Connection,
    project_id: int,
    title: str = "group1",
    parent_id: int | None = None,
    position: int = 0,
) -> int:
    cur = conn.execute(
        "INSERT INTO groups (workspace_id, project_id, title, parent_id, position) "
        "VALUES ((SELECT workspace_id FROM projects WHERE id = ?), ?, ?, ?, ?)",
        (project_id, project_id, title, parent_id, position),
    )
    return cur.lastrowid  # type: ignore[return-value]


def insert_tag(
    conn: sqlite3.Connection,
    workspace_id: int,
    name: str = "tag1",
) -> int:
    cur = conn.execute(
        "INSERT INTO tags (workspace_id, name) VALUES (?, ?)",
        (workspace_id, name),
    )
    return cur.lastrowid  # type: ignore[return-value]


def insert_task_tag(
    conn: sqlite3.Connection,
    task_id: int,
    tag_id: int,
) -> None:
    conn.execute(
        "INSERT INTO task_tags (task_id, tag_id, workspace_id) "
        "VALUES (?, ?, (SELECT workspace_id FROM tasks WHERE id = ?))",
        (task_id, tag_id, task_id),
    )


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
