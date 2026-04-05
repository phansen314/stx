"""Text rendering for CLI output. Pure functions over structured service-layer
types; no DB access, no argparse. Each presenter returns a string ready for
stdout."""

from __future__ import annotations

from .formatting import format_group_num, format_priority, format_task_num, format_timestamp
from .models import Board, Column, Project, Tag, Task, TaskHistory
from .service_models import (
    BoardListView,
    GroupDetail,
    GroupRef,
    MoveToBoardPreview,
    ProjectDetail,
    ProjectGroupTree,
    TaskDetail,
)


def _empty(entity: str) -> str:
    return f"no {entity}s"


def format_history_entry(h: TaskHistory) -> str:
    old_str = h.old_value if h.old_value is not None else "(none)"
    new_str = h.new_value if h.new_value is not None else "(none)"
    return f"{format_timestamp(h.changed_at)}  {h.field}: {old_str} -> {new_str}  ({h.source})"


def format_task_history(history: tuple[TaskHistory, ...]) -> str:
    if not history:
        return "no history"
    return "\n".join(format_history_entry(h) for h in history)


def format_board_list(boards: tuple[Board, ...], active_id: int | None) -> str:
    if not boards:
        return _empty("board")
    lines: list[str] = []
    for b in boards:
        marker = " *" if b.id == active_id else ""
        archived = " (archived)" if b.archived else ""
        lines.append(f"  {b.name}{marker}{archived}")
    return "\n".join(lines)


def format_column_list(cols: tuple[Column, ...]) -> str:
    if not cols:
        return _empty("column")
    return "\n".join(f"  {c.position}  {c.name}" for c in cols)


def format_project_list(projects: tuple[Project, ...]) -> str:
    if not projects:
        return _empty("project")
    lines: list[str] = []
    for p in projects:
        desc = f"  {p.description}" if p.description else ""
        lines.append(f"  {p.name}{desc}")
    return "\n".join(lines)


def format_project_detail(detail: ProjectDetail) -> str:
    lines = [f"{detail.name}"]
    if detail.description:
        lines.append(f"  {detail.description}")
    lines.append(f"  Tasks: {len(detail.tasks)}")
    for t in detail.tasks:
        lines.append(f"    {format_task_num(t.id)}  {t.title}")
    return "\n".join(lines)


def format_tag_list(tags: tuple[Tag, ...]) -> str:
    if not tags:
        return _empty("tag")
    lines: list[str] = []
    for t in tags:
        archived = " (archived)" if t.archived else ""
        lines.append(f"  {t.name}{archived}")
    return "\n".join(lines)


def format_task_detail(detail: TaskDetail) -> str:
    lines = [f"{format_task_num(detail.id)}  {detail.title}"]
    lines.append(f"  Column:      {detail.column.name}")
    if detail.project:
        lines.append(f"  Project:     {detail.project.name}")
    if detail.group is not None:
        lines.append(f"  Group:       {detail.group.title} ({format_group_num(detail.group.id)})")
    if detail.tags:
        tag_str = ", ".join(t.name for t in detail.tags)
        lines.append(f"  Tags:        {tag_str}")
    lines.append(f"  Priority:    {detail.priority}")
    if detail.due_date:
        lines.append(f"  Due:         {format_timestamp(detail.due_date)}")
    lines.append(f"  Created:     {format_timestamp(detail.created_at)}")
    if detail.blocked_by:
        nums = ", ".join(format_task_num(t.id) for t in detail.blocked_by)
        lines.append(f"  Blocked by:  {nums}")
    if detail.blocks:
        nums = ", ".join(format_task_num(t.id) for t in detail.blocks)
        lines.append(f"  Blocks:      {nums}")
    if detail.description:
        lines.append(f"\n  Description:\n    {detail.description}")
    if detail.history:
        lines.append("\n  History:")
        for h in detail.history:
            lines.append(f"    {format_history_entry(h)}")
    return "\n".join(lines)


def format_board_list_view(view: BoardListView) -> str:
    lines: list[str] = []
    for i, col in enumerate(view.columns):
        if i > 0:
            lines.append("")
        lines.append(f"== {col.column.name} ==")
        if not col.tasks:
            lines.append("  (empty)")
            continue
        for item in col.tasks:
            parts = [f"  {format_task_num(item.id)}  {format_priority(item.priority)} {item.title}"]
            if item.project_name:
                parts.append(f"  @{item.project_name}")
            if item.tag_names:
                parts.append(f"  [{', '.join(item.tag_names)}]")
            lines.append("".join(parts))
    return "\n".join(lines)


def format_group_list(
    sections: tuple[tuple[Project, tuple[GroupRef, ...]], ...],
) -> str:
    if not sections:
        return _empty("project")
    non_empty = [(p, refs) for p, refs in sections if refs]
    if not non_empty:
        return _empty("group") if len(sections) == 1 else ""
    show_headers = len(sections) > 1
    lines: list[str] = []
    for proj, refs in non_empty:
        if show_headers:
            lines.append(f"\n== {proj.name} ==")
        for ref in refs:
            archived = " (archived)" if ref.archived else ""
            lines.append(
                f"  {format_group_num(ref.id)}  {ref.title}  "
                f"({len(ref.task_ids)} tasks){archived}"
            )
    return "\n".join(lines)


def format_group_trees(
    sections: tuple[tuple[Project, ProjectGroupTree, dict[int, Task]], ...],
) -> str:
    if not sections:
        return _empty("project")
    show_headers = len(sections) > 1
    lines: list[str] = []
    for proj, tree, task_by_id in sections:
        if not tree.roots and not tree.ungrouped_task_count:
            continue
        if show_headers:
            lines.append(f"\n== {proj.name} ==")
        lines.extend(_format_group_tree_lines(tree, task_by_id))
    if not lines and len(sections) == 1:
        return _empty("group")
    return "\n".join(lines)


def _format_group_tree_lines(
    tree: ProjectGroupTree,
    task_by_id: dict[int, Task],
) -> list[str]:
    lines: list[str] = []

    def _format_subtree(node, prefix: str, is_last: bool) -> None:
        ref = node.group
        connector = "+-- " if prefix else ""
        archived = " (archived)" if ref.archived else ""
        lines.append(f"{prefix}{connector}{format_group_num(ref.id)}  {ref.title}{archived}")
        child_prefix = prefix + ("|   " if not is_last and prefix else "    ") if prefix else ""
        for tid in ref.task_ids:
            task = task_by_id.get(tid)
            if task is None:
                continue
            lines.append(f"{child_prefix}+-- {format_task_num(task.id)}: {task.title}")
        for i, child in enumerate(node.children):
            _format_subtree(child, child_prefix, i == len(node.children) - 1)

    for i, root in enumerate(tree.roots):
        _format_subtree(root, "", i == len(tree.roots) - 1)

    if tree.ungrouped_task_count:
        lines.append(f"\n({tree.ungrouped_task_count} ungrouped tasks)")
    return lines


def format_group_detail(
    detail: GroupDetail,
    project_name: str,
    ancestry_titles: tuple[str, ...],
) -> str:
    lines = [f"Group: {detail.title} ({format_group_num(detail.id)})"]
    lines.append(f"  Project: {project_name}")
    lines.append(f"  Path:    {' > '.join(ancestry_titles)}")
    lines.append(f"  Tasks:   {len(detail.tasks)}")
    if detail.children:
        child_names = ", ".join(c.title for c in detail.children)
        lines.append(f"  Sub-groups: {child_names}")
    if detail.tasks:
        lines.append("")
        for t in detail.tasks:
            due = f"  due: {format_timestamp(t.due_date)}" if t.due_date else ""
            lines.append(
                f"  {format_task_num(t.id)}  {format_priority(t.priority)} {t.title}{due}"
            )
    return "\n".join(lines)


def format_move_preview(
    preview: MoveToBoardPreview,
    target_board_name: str,
    target_col_name: str,
) -> str:
    lines = [f"dry-run: would transfer {format_task_num(preview.task_id)} ({preview.task_title})"]
    lines.append(
        f"  from board {preview.source_board_id} -> "
        f"board '{target_board_name}' / column '{target_col_name}'"
    )
    if not preview.can_move:
        if preview.dependency_ids:
            dep_list = ", ".join(format_task_num(d) for d in preview.dependency_ids)
            lines.append(f"  \u26a0 has dependencies: {dep_list}")
            lines.append("  move would FAIL \u2014 remove dependencies first")
        else:
            lines.append(f"  \u26a0 {preview.blocking_reason}")
            lines.append("  move would FAIL")
    else:
        lines.append("  no dependencies \u2014 transfer OK")
    return "\n".join(lines)
