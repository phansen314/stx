from __future__ import annotations

import dataclasses
from datetime import date, datetime, timezone
from enum import StrEnum
from time import gmtime, strftime
from typing import Any


def format_task_num(task_id: int) -> str:
    return f"task-{task_id:04d}"


def format_group_num(group_id: int) -> str:
    return f"group-{group_id:04d}"


def format_priority(priority: int) -> str:
    return f"[P{priority}]"


def parse_date(raw: str) -> int:
    """YYYY-MM-DD -> Unix epoch int."""
    try:
        d = date.fromisoformat(raw)
    except ValueError:
        raise ValueError(f"invalid date: {raw!r} (expected YYYY-MM-DD)") from None
    dt = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
    return int(dt.timestamp())


def format_timestamp(epoch: int) -> str:
    return strftime("%Y-%m-%d", gmtime(epoch))


def to_dict(obj: Any) -> Any:
    """Convert dataclasses (possibly nested) to plain dicts for JSON serialization.

    Handles StrEnum -> .value, tuples/lists, nested dataclasses, and plain dicts
    with dataclass values. Does *not* use dataclasses.asdict() which recurses
    incorrectly for StrEnum.
    """
    if isinstance(obj, StrEnum):
        return obj.value
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {
            f.name: to_dict(getattr(obj, f.name))
            for f in dataclasses.fields(obj)
        }
    if isinstance(obj, dict):
        return {k: to_dict(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_dict(item) for item in obj]
    return obj
