from __future__ import annotations

import os
import sqlite3
from collections.abc import Generator
from pathlib import Path

import pytest

from sticky_notes import service
from sticky_notes.connection import get_connection, init_db
from tests.seed import seed_multi_workspace, seed_workspace


def pytest_configure(config):
    """Enable coverage in xdist workers by setting COVERAGE_PROCESS_START."""
    os.environ.setdefault("COVERAGE_PROCESS_START", "pyproject.toml")


@pytest.fixture
def config_path(tmp_path: Path) -> Path:
    return tmp_path / "tui.toml"


@pytest.fixture(autouse=True)
def _isolate_config_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirect DEFAULT_CONFIG_PATH to a per-test tmp location.

    Prevents any test from reading or writing ~/.config/sticky-notes/tui.toml,
    whether via StickyNotesApp() with no config_path, load_config() with no arg,
    or save_config() falling back to the default.
    """
    safe = tmp_path / "tui.toml"
    monkeypatch.setattr("sticky_notes.tui.config.DEFAULT_CONFIG_PATH", safe)
    monkeypatch.setattr("sticky_notes.tui.app.DEFAULT_CONFIG_PATH", safe)


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "test.db"


@pytest.fixture
def conn(db_path: Path) -> Generator[sqlite3.Connection, None, None]:
    c = get_connection(db_path)
    init_db(c)
    yield c
    if c.in_transaction:
        c.rollback()
    c.close()


@pytest.fixture
def seeded_tui_db(tmp_path: Path) -> tuple[Path, dict]:
    db_path = tmp_path / "tui-seeded.db"
    c = get_connection(db_path)
    init_db(c)
    ids = seed_workspace(c, db_path=db_path)
    c.close()
    return db_path, ids


@pytest.fixture
def multi_workspace_tui_db(tmp_path: Path) -> tuple[Path, dict]:
    db_path = tmp_path / "tui-multi.db"
    c = get_connection(db_path)
    init_db(c)
    ids = seed_multi_workspace(c, db_path=db_path)
    c.close()
    return db_path, ids


@pytest.fixture
def seeded_tui_db_empty_middle(tmp_path: Path) -> tuple[Path, dict]:
    """Seeded workspace with all In Progress tasks archived (empty middle column)."""
    db_path = tmp_path / "tui-seeded-empty-mid.db"
    c = get_connection(db_path)
    init_db(c)
    ids = seed_workspace(c, db_path=db_path)
    service.update_task(c, ids["task_ids"]["auth_middleware"], {"archived": True}, "test")
    service.update_task(c, ids["task_ids"]["unit_tests"], {"archived": True}, "test")
    c.close()
    return db_path, ids
