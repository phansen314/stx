from __future__ import annotations

from datetime import UTC, date, datetime
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


def node_display_id(node_type: str, node_id: int) -> str:
    if node_type == "task":
        return format_task_num(node_id)
    elif node_type == "group":
        return format_group_num(node_id)
    elif node_type == "status":
        return f"st{node_id}"
    return f"ws{node_id}"


def format_priority(priority: int) -> str:
    return f"[P{priority}]"


def parse_date(raw: str) -> int:
    """YYYY-MM-DD -> Unix epoch int."""
    try:
        d = date.fromisoformat(raw)
    except ValueError:
        raise ValueError(f"invalid date: {raw!r} (expected YYYY-MM-DD)") from None
    dt = datetime(d.year, d.month, d.day, tzinfo=UTC)
    return int(dt.timestamp())


def format_timestamp(epoch: int) -> str:
    return strftime("%Y-%m-%d", gmtime(epoch))
