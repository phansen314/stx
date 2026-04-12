from __future__ import annotations

from pathlib import Path


def active_workspace_path(db_path: Path) -> Path:
    """Return the legacy active-workspace pointer file path.

    Deprecated: active workspace is now stored in tui.toml. This function is
    retained for `stx info` output and the one-release legacy read fallback.
    """
    return db_path.parent / "active-workspace"


def get_active_workspace_id(config_path: Path, db_path: Path) -> int | None:
    """Return the active workspace ID, or None if none is set.

    Reads from tui.toml (config_path) first. Falls back to the legacy pointer
    file (deprecated, read-only) if tui.toml has no active_workspace set.

    Raises ValueError if the legacy file exists but contains invalid data.
    """
    from stx.tui.config import load_config  # lazy — avoids circular import

    config_value = load_config(config_path).active_workspace
    if config_value is not None:
        return config_value
    # Legacy fallback — deprecated, no writes go here any more
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
            "run 'stx workspace use NAME' to reset it"
        )


def set_active_workspace_id(config_path: Path, workspace_id: int) -> None:
    from stx.tui.config import load_config, save_config  # lazy — avoids circular import

    cfg = load_config(config_path)
    cfg.active_workspace = workspace_id
    save_config(cfg, config_path)


def clear_active_workspace_id(config_path: Path) -> None:
    from stx.tui.config import load_config, save_config  # lazy — avoids circular import

    cfg = load_config(config_path)
    cfg.active_workspace = None
    save_config(cfg, config_path)
