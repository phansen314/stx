"""Client-side DTOs mirroring the daemon's JSON (snake_case here, camelCase on the wire)."""
from __future__ import annotations

import re
from dataclasses import dataclass, fields
from typing import Any, TypeVar

T = TypeVar("T")


def _snake(s: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", s).lower()


def _camel(s: str) -> str:
    """snake_case -> camelCase; idempotent on camelCase input (no `_[a-z]` to rewrite).
    Lets edit_* callers pass either spelling without the daemon silently dropping the field
    (its JSON decoder ignores unknown keys, so a snake_case key would be a silent no-op)."""
    return re.sub(r"_([a-z])", lambda m: m.group(1).upper(), s)


def build(cls: type[T], d: dict[str, Any]) -> T:
    """Construct a dataclass from a wire dict, mapping camelCase keys and ignoring extras.
    All dataclass fields have defaults, so partial payloads (e.g. frontier rows) work."""
    known = {f.name for f in fields(cls)}  # type: ignore[arg-type]
    kw = {_snake(k): v for k, v in d.items() if _snake(k) in known}
    return cls(**kw)  # type: ignore[call-arg]


@dataclass(frozen=True)
class Workspace:
    id: int = 0
    name: str = ""
    metadata_json: str = "{}"
    archived: bool = False
    version: int = 0
    created_at: str = ""
    updated_at: str = ""


@dataclass(frozen=True)
class Track:
    id: int = 0
    workspace_id: int = 0
    name: str = ""
    description: str = ""
    metadata_json: str = "{}"
    archived: bool = False
    version: int = 0
    created_at: str = ""
    updated_at: str = ""


@dataclass(frozen=True)
class Segment:
    id: int = 0
    workspace_id: int = 0
    track_id: int = 0
    parent_segment_id: int | None = None
    name: str = ""
    is_root: bool = False
    archived: bool = False
    created_at: str = ""


@dataclass(frozen=True)
class Status:
    id: int = 0
    workspace_id: int = 0
    name: str = ""
    kanban_order: int = 0
    terminal: bool = False
    is_default: bool = False
    archived: bool = False
    created_at: str = ""


@dataclass(frozen=True)
class Kind:
    id: int = 0
    workspace_id: int = 0
    name: str = ""
    archived: bool = False
    created_at: str = ""


@dataclass(frozen=True)
class Transition:
    id: int = 0
    workspace_id: int = 0
    from_status_id: int = 0
    to_status_id: int = 0
    archived: bool = False


@dataclass(frozen=True)
class Task:
    id: int = 0
    workspace_id: int = 0
    segment_id: int = 0
    status_id: int = 0
    kind_id: int | None = None
    title: str = ""
    description: str = ""
    priority: int = 0
    metadata_json: str = "{}"
    archived: bool = False
    version: int = 0
    created_at: str = ""
    updated_at: str = ""
