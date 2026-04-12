from __future__ import annotations

import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path

DEFAULT_CONFIG_PATH = Path.home() / ".config" / "sticky-notes" / "tui.toml"


@dataclass
class TuiConfig:
    theme: str = "dark"
    show_task_descriptions: bool = True
    show_archived: bool = False
    confirm_archive: bool = True
    default_priority: int = 1
    auto_refresh_seconds: int = 30
    active_workspace: int | None = None
    status_order: dict[int, list[int]] = field(default_factory=dict)


def load_config(path: Path | None = None) -> TuiConfig:
    if path is None:
        path = DEFAULT_CONFIG_PATH
    config = TuiConfig()
    if not path.exists():
        return config
    with open(path, "rb") as f:
        data = tomllib.load(f)
    for fld in fields(TuiConfig):
        if fld.name in data:
            raw = data[fld.name]
            if fld.name == "status_order":
                if isinstance(raw, dict):
                    setattr(config, fld.name, {int(k): v for k, v in raw.items()})
                # Ignore legacy flat list format — no workspace association
            else:
                setattr(config, fld.name, raw)
    return config


def save_config(config: TuiConfig, path: Path | None = None) -> None:
    if path is None:
        path = DEFAULT_CONFIG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    for fld in fields(config):
        value = getattr(config, fld.name)
        if isinstance(value, bool):
            lines.append(f"{fld.name} = {str(value).lower()}")
        elif isinstance(value, int):
            lines.append(f"{fld.name} = {value}")
        elif isinstance(value, str):
            lines.append(f'{fld.name} = "{value}"')
        elif value is None:
            pass  # omit None fields — None is not valid TOML
        elif isinstance(value, dict):
            lines.append(f"\n[{fld.name}]")
            for k, v in value.items():
                items = ", ".join(str(i) for i in v)
                lines.append(f"{k} = [{items}]")
        elif isinstance(value, list):
            items = ", ".join(str(v) for v in value)
            lines.append(f"{fld.name} = [{items}]")
    path.write_text("\n".join(lines) + "\n")
