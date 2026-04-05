from __future__ import annotations

from datetime import date, datetime, timezone
from time import gmtime, strftime


def format_task_num(task_id: int) -> str:
    return f"task-{task_id:04d}"


def parse_task_num(raw: str) -> int:
    """Accept '1', '0001', 'task-0001', '#1'."""
    s = raw.strip().lower()
    if s.startswith("task-"):
        s = s[5:]
    elif s.startswith("#"):
        s = s[1:]
    try:
        n = int(s)
    except ValueError:
        raise ValueError(f"invalid task number: {raw!r}") from None
    if n <= 0:
        raise ValueError(f"invalid task number: {raw!r}")
    return n


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


