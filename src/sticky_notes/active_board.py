from __future__ import annotations

from pathlib import Path


def active_board_path(db_path: Path) -> Path:
    return db_path.parent / "active-board"


def get_active_board_id(db_path: Path) -> int | None:
    """Return the active board ID, or None if none is set.

    Raises ValueError if the pointer file exists but contains invalid data.
    """
    p = active_board_path(db_path)
    try:
        text = p.read_text().strip()
    except FileNotFoundError:
        return None
    try:
        return int(text)
    except ValueError:
        raise ValueError(
            f"active-board pointer is corrupt (got {text!r}); "
            "run 'todo board use NAME' to reset it"
        )


def set_active_board_id(db_path: Path, board_id: int) -> None:
    p = active_board_path(db_path)
    p.write_text(str(board_id))


def clear_active_board_id(db_path: Path) -> None:
    active_board_path(db_path).unlink(missing_ok=True)
