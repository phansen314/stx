from __future__ import annotations

from pathlib import Path


def active_board_path(db_path: Path) -> Path:
    return db_path.parent / "active-board"


def get_active_board_id(db_path: Path) -> int | None:
    p = active_board_path(db_path)
    try:
        text = p.read_text().strip()
        return int(text)
    except (FileNotFoundError, ValueError):
        return None


def set_active_board_id(db_path: Path, board_id: int) -> None:
    p = active_board_path(db_path)
    p.write_text(str(board_id))
