from __future__ import annotations

import tomllib
from dataclasses import dataclass, fields
from pathlib import Path

DEFAULT_CONFIG_PATH = (
    Path.home() / ".config" / "sticky-notes" / "tui.toml"
)


@dataclass
class TuiConfig:
    theme: str = "dark"
    show_task_descriptions: bool = True
    show_archived: bool = False
    confirm_archive: bool = True
    default_priority: int = 1


def load_config(path: Path = DEFAULT_CONFIG_PATH) -> TuiConfig:
    config = TuiConfig()
    if not path.exists():
        return config
    with open(path, "rb") as f:
        data = tomllib.load(f)
    for field in fields(TuiConfig):
        if field.name in data:
            setattr(config, field.name, data[field.name])
    return config


def save_config(config: TuiConfig, path: Path = DEFAULT_CONFIG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    for field in fields(config):
        value = getattr(config, field.name)
        if isinstance(value, bool):
            lines.append(f"{field.name} = {str(value).lower()}")
        elif isinstance(value, int):
            lines.append(f"{field.name} = {value}")
        elif isinstance(value, str):
            lines.append(f'{field.name} = "{value}"')
    path.write_text("\n".join(lines) + "\n")
