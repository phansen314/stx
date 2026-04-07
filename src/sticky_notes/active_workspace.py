from __future__ import annotations

from pathlib import Path


def active_workspace_path(db_path: Path) -> Path:
    return db_path.parent / "active-workspace"


def get_active_workspace_id(db_path: Path) -> int | None:
    """Return the active workspace ID, or None if none is set.

    Raises ValueError if the pointer file exists but contains invalid data.
    """
    p = active_workspace_path(db_path)
    try:
        text = p.read_text().strip()
    except FileNotFoundError:
        return None
    try:
        return int(text)
    except ValueError:
        raise ValueError(
            f"active-workspace pointer is corrupt (got {text!r}); "
            "run 'todo workspace use NAME' to reset it"
        )


def set_active_workspace_id(db_path: Path, workspace_id: int) -> None:
    p = active_workspace_path(db_path)
    p.write_text(str(workspace_id))


def clear_active_workspace_id(db_path: Path) -> None:
    active_workspace_path(db_path).unlink(missing_ok=True)
