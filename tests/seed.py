from __future__ import annotations

import sqlite3
from pathlib import Path

from stx import service
from stx.active_workspace import set_active_workspace_id
from stx.connection import get_connection, init_db


def seed_workspace(conn: sqlite3.Connection, db_path: Path | None = None) -> dict:
    workspace = service.create_workspace(conn, "Coding")

    todo = service.create_status(conn, workspace.id, "Todo")
    in_progress = service.create_status(conn, workspace.id, "In Progress")
    done = service.create_status(conn, workspace.id, "Done")

    # Root group replacing old "apr-api" project
    apr_api = service.create_group(
        conn,
        workspace.id,
        "apr-api",
        description="April API sprint",
    )

    t1 = service.create_task(
        conn,
        workspace.id,
        "Design API schema",
        todo.id,
        group_id=apr_api.id,
        priority=3,
        description="Define OpenAPI spec for all endpoints",
    )
    t2 = service.create_task(
        conn,
        workspace.id,
        "Endpoint design",
        todo.id,
        group_id=apr_api.id,
        priority=2,
    )
    t3 = service.create_task(
        conn,
        workspace.id,
        "Auth middleware",
        in_progress.id,
        group_id=apr_api.id,
        priority=3,
        description="JWT validation and role extraction",
    )
    t4 = service.create_task(
        conn,
        workspace.id,
        "User CRUD",
        todo.id,
        priority=2,
        description="Create, read, update, delete users",
    )
    t5 = service.create_task(
        conn,
        workspace.id,
        "Write unit tests",
        in_progress.id,
        priority=1,
    )
    t6 = service.create_task(
        conn,
        workspace.id,
        "Setup CI pipeline",
        done.id,
        priority=2,
        description="GitHub Actions workflow",
    )
    t7 = service.create_task(
        conn,
        workspace.id,
        "Database migrations",
        todo.id,
        group_id=apr_api.id,
        priority=3,
    )
    t8 = service.create_task(
        conn,
        workspace.id,
        "Scaffold project",
        done.id,
        priority=1,
    )

    # Auth middleware blocked by endpoint design
    service.add_task_edge(conn, t3.id, t2.id, kind="blocks")
    # User CRUD blocked by auth middleware
    service.add_task_edge(conn, t4.id, t3.id, kind="blocks")

    if db_path is not None:
        config_path = db_path.parent / "tui.toml"
        set_active_workspace_id(config_path, workspace.id)

    return {
        "workspace_id": workspace.id,
        "status_ids": {"todo": todo.id, "in_progress": in_progress.id, "done": done.id},
        "group_id": apr_api.id,
        "task_ids": {
            "design_api": t1.id,
            "endpoint_design": t2.id,
            "auth_middleware": t3.id,
            "user_crud": t4.id,
            "unit_tests": t5.id,
            "ci_pipeline": t6.id,
            "db_migrations": t7.id,
            "scaffold": t8.id,
        },
    }


def seed_multi_workspace(conn: sqlite3.Connection, db_path: Path | None = None) -> dict:
    ids1 = seed_workspace(conn, db_path=db_path)
    ws2 = service.create_workspace(conn, "Personal")
    backlog = service.create_status(conn, ws2.id, "Backlog")
    complete = service.create_status(conn, ws2.id, "Complete")
    home = service.create_group(conn, ws2.id, "Home")
    t_a = service.create_task(conn, ws2.id, "Buy groceries", backlog.id, group_id=home.id)
    t_b = service.create_task(conn, ws2.id, "Fix fence", complete.id)
    return {
        "ws1": ids1,
        "ws2": {
            "workspace_id": ws2.id,
            "status_ids": {"backlog": backlog.id, "complete": complete.id},
            "group_id": home.id,
            "task_ids": {"buy_groceries": t_a.id, "fix_fence": t_b.id},
        },
    }


if __name__ == "__main__":
    import sys

    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("tmp/test.db")
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = get_connection(path)
    init_db(conn)
    ids = seed_workspace(conn, db_path=path)
    conn.close()
    print(f"Seeded {path} with workspace {ids['workspace_id']}")
