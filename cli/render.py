"""Compact, token-frugal text renderers (default) + a --json escape hatch.

Text mode drops noisy fields (timestamps, metadataJson, version) and prefers names over ids.
JSON mode dumps the underlying dataclasses verbatim for piping to jq.
"""
from __future__ import annotations

import dataclasses
import json
from typing import Any


def _default(o: Any):
    if dataclasses.is_dataclass(o):
        return dataclasses.asdict(o)
    raise TypeError(f"not JSON-serializable: {type(o)}")


def dumps(obj: Any) -> str:
    return json.dumps(obj, default=_default, indent=2)


def _prio(p: int) -> str:
    return f"P{p}" if p else "  "


def workspaces(rows: list[tuple]) -> str:
    # rows: (workspace, n_tracks)
    if not rows:
        return "(no workspaces)"
    return "\n".join(f"{ws.id:>4}  {ws.name}  ({n} track{'s' if n != 1 else ''})" for ws, n in rows)


def relates_kinds(items: list[str]) -> str:
    # relates_to.kind is free text by design (D6); this just lists what's in live use.
    if not items:
        return "(no relation kinds in use)"
    return "\n".join(items)


def frontier(items: list, status_names: dict[int, str]) -> str:
    if not items:
        return "(nothing ready)"
    lines = []
    for it in items:
        st = status_names.get(it.status_id, str(it.status_id))
        lines.append(f"{it.id:>4}  {_prio(it.priority)}  [{st}]  {it.title}")
    return "\n".join(lines)


def task_detail(detail: dict, status_names: dict[int, str], kind_names: dict[int, str]) -> str:
    t = detail["task"]
    st = status_names.get(t["statusId"], str(t["statusId"]))
    kn = kind_names.get(t["kindId"], "-") if t.get("kindId") else "-"
    out = [
        f"#{t['id']}  {t['title']}",
        f"  status: {st}    kind: {kn}    priority: P{t['priority']}"
        + ("    ARCHIVED" if t.get("archived") else ""),
    ]
    if t.get("description"):
        out.append(f"  description: {t['description']}")
    if detail.get("blocksIn"):
        out.append(f"  blocked-by: {', '.join('#' + str(i) for i in detail['blocksIn'])}")
    if detail.get("blocksOut"):
        out.append(f"  blocks: {', '.join('#' + str(i) for i in detail['blocksOut'])}")
    if detail.get("relates"):
        rel = ", ".join(f"{e['kind']}→#{e['otherTaskId']}" if e["outgoing"]
                        else f"{e['kind']}←#{e['otherTaskId']}" for e in detail["relates"])
        out.append(f"  relates: {rel}")
    return "\n".join(out)


def tree(ws, blocks: list, status_names: dict[int, str]) -> str:
    """blocks: list of (track, segments, tasks). Mirrors the TUI tree: root-segment tasks hang
    directly under the track; nested segments recurse."""
    lines = [f"{ws.name} (#{ws.id})"]

    def task_line(t, depth: int) -> str:
        st = status_names.get(t.status_id, str(t.status_id))
        return f"{'  ' * depth}- #{t.id} {_prio(t.priority)} [{st}] {t.title}"

    for track, segments, tasks in blocks:
        lines.append(f"  ▸ {track.name} (#{track.id})")
        by_parent: dict[int | None, list] = {}
        root = None
        for s in segments:
            by_parent.setdefault(s.parent_segment_id, []).append(s)
            if s.is_root:
                root = s
        tasks_by_seg: dict[int, list] = {}
        for t in tasks:
            tasks_by_seg.setdefault(t.segment_id, []).append(t)

        def emit_seg(seg, depth: int):
            lines.append(f"{'  ' * depth}▫ {seg.name} (#{seg.id})")
            for child in by_parent.get(seg.id, []):
                emit_seg(child, depth + 1)
            for t in tasks_by_seg.get(seg.id, []):
                lines.append(task_line(t, depth + 1))

        if root is not None:
            for t in tasks_by_seg.get(root.id, []):
                lines.append(task_line(t, 2))
            for child in by_parent.get(root.id, []):
                emit_seg(child, 2)
    if len(lines) == 1:
        lines.append("  (empty)")
    return "\n".join(lines)
