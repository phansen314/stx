"""Local, per-user TUI preferences persisted as JSON (stdlib only). NOT daemon state — a small
last-write-wins file under $XDG_CONFIG_HOME/stx/tui.json (falling back to ~/.config). Loading is
defensive: any missing/corrupt/wrong-typed value falls back to DEFAULTS."""
from __future__ import annotations

import json
import os
from pathlib import Path

DEFAULTS: dict = {"theme": "textual-dark", "refresh_secs": 2.0}
_MIN_REFRESH, _MAX_REFRESH = 0.5, 3600.0


def _config_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return Path(base) / "stx" / "tui.json"


def _clamp_refresh(v: float) -> float:
    return max(_MIN_REFRESH, min(_MAX_REFRESH, float(v)))


def load_config() -> dict:
    cfg = dict(DEFAULTS)
    try:
        data = json.loads(_config_path().read_text())
    except (OSError, ValueError):
        return cfg
    if not isinstance(data, dict):
        return cfg
    if isinstance(data.get("theme"), str):
        cfg["theme"] = data["theme"]
    r = data.get("refresh_secs")
    if isinstance(r, (int, float)) and not isinstance(r, bool) and r > 0:
        cfg["refresh_secs"] = _clamp_refresh(r)
    return cfg


def save_config(cfg: dict) -> None:
    """Best-effort persist (never raises — a preference file failing to write must not crash the UI)."""
    body = {"theme": cfg.get("theme", DEFAULTS["theme"]),
            "refresh_secs": _clamp_refresh(cfg.get("refresh_secs", DEFAULTS["refresh_secs"]))}
    try:
        p = _config_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(body, indent=2))
    except OSError:
        pass
