from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Generator

import pytest

from sticky_notes.connection import get_connection, init_db


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
