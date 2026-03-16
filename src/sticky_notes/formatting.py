from __future__ import annotations

from datetime import date, datetime, timezone
from time import gmtime, strftime


def format_task_num(task_id: int) -> str:
    return f"task-{task_id:04d}"


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
