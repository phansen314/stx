from __future__ import annotations

import sqlite3
from pathlib import Path

from sticky_notes import service
from sticky_notes.active_board import set_active_board_id
from sticky_notes.connection import get_connection, init_db


def seed_board(conn: sqlite3.Connection, db_path: Path | None = None) -> dict:
    board = service.create_board(conn, "Coding")

    todo = service.create_column(conn, board.id, "Todo", position=0)
    in_progress = service.create_column(conn, board.id, "In Progress", position=1)
    done = service.create_column(conn, board.id, "Done", position=2)

    project = service.create_project(
        conn, board.id, "apr-api", description="April API sprint"
    )

    t1 = service.create_task(
        conn, board.id, "Design API schema", todo.id,
        project_id=project.id, priority=3,
        description="Define OpenAPI spec for all endpoints",
    )
    t2 = service.create_task(
        conn, board.id, "Endpoint design", todo.id,
        project_id=project.id, priority=2,
    )
    t3 = service.create_task(
        conn, board.id, "Auth middleware", in_progress.id,
        project_id=project.id, priority=3,
        description="JWT validation and role extraction",
    )
    t4 = service.create_task(
        conn, board.id, "User CRUD", todo.id,
        priority=2,
        description="Create, read, update, delete users",
    )
    t5 = service.create_task(
        conn, board.id, "Write unit tests", in_progress.id,
        priority=1,
    )
    t6 = service.create_task(
        conn, board.id, "Setup CI pipeline", done.id,
        priority=2,
        description="GitHub Actions workflow",
    )
    t7 = service.create_task(
        conn, board.id, "Database migrations", todo.id,
        project_id=project.id, priority=3,
    )
    t8 = service.create_task(
        conn, board.id, "Scaffold project", done.id,
        priority=1,
    )

    # Auth middleware blocked by endpoint design
    service.add_dependency(conn, t3.id, t2.id)
    # User CRUD blocked by auth middleware
    service.add_dependency(conn, t4.id, t3.id)

    if db_path is not None:
        set_active_board_id(db_path, board.id)

    return {
        "board_id": board.id,
        "column_ids": {"todo": todo.id, "in_progress": in_progress.id, "done": done.id},
        "project_id": project.id,
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


if __name__ == "__main__":
    import sys

    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("tmp/test.db")
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = get_connection(path)
    init_db(conn)
    ids = seed_board(conn, db_path=path)
    conn.close()
    print(f"Seeded {path} with board {ids['board_id']}")
