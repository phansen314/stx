"""Text rendering for CLI output. Pure functions over structured service-layer
types; no DB access, no argparse. Each presenter returns a string ready for
stdout."""

from __future__ import annotations

from dataclasses import fields

from .formatting import format_group_num, format_priority, format_task_num, format_timestamp
from .models import Project, Status, Tag, TaskHistory, Workspace
from .service_models import (
    ArchivePreview,
    EntityUpdatePreview,
    GroupDetail,
    GroupRef,
    MoveToWorkspacePreview,
    ProjectDetail,
    TaskDetail,
    TaskMovePreview,
    WorkspaceContext,
    WorkspaceListView,
)


def _empty(entity: str) -> str:
    return f"no {entity}s"


def format_metadata_block(metadata: dict[str, str], indent: int = 2) -> str:
    """Render a metadata dict as indented 'key: value' lines.

    Returns an empty string when the dict is empty (callers can skip the
    'Metadata:' header entirely in that case).
    """
    if not metadata:
        return ""
    pad = " " * indent
    return "\n".join(f"{pad}{k}: {v}" for k, v in sorted(metadata.items()))


def format_history_entry(h: TaskHistory) -> str:
    old_str = h.old_value if h.old_value is not None else "(none)"
    new_str = h.new_value if h.new_value is not None else "(none)"
    return f"{format_timestamp(h.changed_at)}  {h.field}: {old_str} -> {new_str}  ({h.source})"


def format_task_history(history: tuple[TaskHistory, ...]) -> str:
    if not history:
        return "no history"
    return "\n".join(format_history_entry(h) for h in history)


def format_workspace_list(workspaces: tuple[Workspace, ...], active_id: int | None) -> str:
    if not workspaces:
        return _empty("workspace")
    lines: list[str] = []
    for w in workspaces:
        marker = " *" if w.id == active_id else ""
        archived = " (archived)" if w.archived else ""
        lines.append(f"  {w.name}{marker}{archived}")
    return "\n".join(lines)


def format_status_list(statuses: tuple[Status, ...]) -> str:
    if not statuses:
        return "no statuses"
    lines: list[str] = []
    for s in statuses:
        archived = " (archived)" if s.archived else ""
        lines.append(f"  {s.name}{archived}")
    return "\n".join(lines)


def format_project_list(projects: tuple[Project, ...]) -> str:
    if not projects:
        return _empty("project")
    lines: list[str] = []
    for p in projects:
        archived = " (archived)" if p.archived else ""
        desc = f"  {p.description}" if p.description else ""
        lines.append(f"  {p.name}{archived}{desc}")
    return "\n".join(lines)


def format_project_detail(detail: ProjectDetail) -> str:
    lines = [f"{detail.name}"]
    if detail.description:
        lines.append(f"  {detail.description}")
    if detail.metadata:
        lines.append("  Metadata:")
        lines.append(format_metadata_block(detail.metadata, indent=4))
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
    lines.append(f"  Status:      {detail.status.name}")
    if detail.project:
        lines.append(f"  Project:     {detail.project.name}")
    if detail.group is not None:
        lines.append(f"  Group:       {detail.group.title} ({format_group_num(detail.group.id)})")
    if detail.tags:
        tag_str = ", ".join(t.name for t in detail.tags)
        lines.append(f"  Tags:        {tag_str}")
    if detail.metadata:
        lines.append("  Metadata:")
        lines.append(format_metadata_block(detail.metadata, indent=4))
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


def format_workspace_list_view(view: WorkspaceListView) -> str:
    lines: list[str] = []
    for i, col in enumerate(view.statuses):
        if i > 0:
            lines.append("")
        lines.append(f"== {col.status.name} ==")
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


def format_workspace_context(ctx: WorkspaceContext) -> str:
    lines: list[str] = [f"== {ctx.view.workspace.name} =="]
    if ctx.view.workspace.metadata:
        lines.append("Metadata:")
        lines.append(format_metadata_block(ctx.view.workspace.metadata, indent=2))
    view_str = format_workspace_list_view(ctx.view)
    if view_str:
        lines.append(view_str)
    if ctx.projects:
        lines.append(f"Projects: {', '.join(p.name for p in ctx.projects)}")
    if ctx.tags:
        lines.append(f"Tags: {', '.join(t.name for t in ctx.tags)}")
    if ctx.groups:
        proj_name = {p.id: p.name for p in ctx.projects}
        group_strs = [f"{g.title} ({proj_name.get(g.project_id, '?')})" for g in ctx.groups]
        lines.append(f"Groups: {', '.join(group_strs)}")
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
                f"  {format_group_num(ref.id)}  {ref.title}  ({len(ref.task_ids)} tasks){archived}"
            )
    return "\n".join(lines)


def format_group_detail(
    detail: GroupDetail,
    project_name: str,
    ancestry_titles: tuple[str, ...],
) -> str:
    lines = [f"{format_group_num(detail.id)}  {detail.title}"]
    if detail.description:
        lines.append(f"  Description: {detail.description}")
    lines.append(f"  Project:     {project_name}")
    lines.append(f"  Path:        {' > '.join(ancestry_titles)}")
    lines.append(f"  Tasks:       {len(detail.tasks)}")
    if detail.metadata:
        lines.append("  Metadata:")
        lines.append(format_metadata_block(detail.metadata, indent=4))
    if detail.children:
        child_names = ", ".join(c.title for c in detail.children)
        lines.append(f"  Sub-groups: {child_names}")
    if detail.tasks:
        lines.append("")
        for t in detail.tasks:
            due = f"  due: {format_timestamp(t.due_date)}" if t.due_date else ""
            lines.append(f"  {format_task_num(t.id)}  {format_priority(t.priority)} {t.title}{due}")
    return "\n".join(lines)


def format_move_preview(
    preview: MoveToWorkspacePreview,
    target_workspace_name: str,
    target_status_name: str,
    *,
    source_workspace_name: str,
    target_project_name: str | None = None,
) -> str:
    lines = [f"dry-run: would transfer {format_task_num(preview.task_id)} ({preview.task_title})"]
    dest = f"workspace '{target_workspace_name}' / status '{target_status_name}'"
    if target_project_name:
        dest += f" / project '{target_project_name}'"
    lines.append(f"  from workspace '{source_workspace_name}' -> {dest}")
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


def format_archive_preview(preview: ArchivePreview) -> str:
    if preview.already_archived:
        return f"{preview.entity_type} '{preview.entity_name}' is already archived; nothing to do"
    total = preview.task_count + preview.group_count + preview.project_count + preview.status_count
    lines = [f"would archive {preview.entity_type} '{preview.entity_name}'"]
    if total == 0:
        return lines[0]
    if preview.project_count:
        lines.append(f"  projects: {preview.project_count}")
    if preview.group_count:
        group_label = "descendant groups" if preview.entity_type == "group" else "groups"
        lines.append(f"  {group_label}: {preview.group_count}")
    if preview.status_count:
        lines.append(f"  statuses: {preview.status_count}")
    if preview.task_count:
        lines.append(f"  tasks: {preview.task_count}")
    return "\n".join(lines)


def _fmt_diff_value(value: object) -> str:
    """Format a before/after value for human-readable diff output.

    Strings render with explicit single quotes (`'foo'`), None renders as
    `(none)`, everything else renders via `str()` (ints, bools). Shared
    across `format_entity_update_preview` and `format_task_move_preview`
    for consistency.
    """
    if value is None:
        return "(none)"
    if isinstance(value, str):
        return f"'{value}'"
    return str(value)


def format_entity_update_preview(preview: EntityUpdatePreview) -> str:
    if preview.entity_type == "task":
        header = f"{format_task_num(preview.entity_id)} ({preview.label})"
    elif preview.entity_type == "group":
        header = f"{format_group_num(preview.entity_id)} ({preview.label})"
    else:
        # Projects don't have a numeric handle — names are unique within
        # a workspace, so the label alone is the canonical identifier.
        header = f"project '{preview.label}'"
    lines = [f"dry-run: would update {header}"]
    has_body = False
    for key in preview.after:
        before = preview.before.get(key)
        after = preview.after[key]
        lines.append(f"  {key}: {_fmt_diff_value(before)} -> {_fmt_diff_value(after)}")
        has_body = True
    for tag in preview.tags_added:
        lines.append(f"  +tag {tag}")
        has_body = True
    for tag in preview.tags_removed:
        lines.append(f"  -tag {tag}")
        has_body = True
    if not has_body:
        lines.append("  (no changes)")
    return "\n".join(lines)


def format_task_move_preview(preview: TaskMovePreview) -> str:
    lines = [f"dry-run: would move {format_task_num(preview.task_id)} ({preview.title})"]
    lines.append(
        f"  status: {_fmt_diff_value(preview.from_status)} -> {_fmt_diff_value(preview.to_status)}"
    )
    lines.append(
        f"  position: {_fmt_diff_value(preview.from_position)} -> {_fmt_diff_value(preview.to_position)}"
    )
    if preview.project_changed:
        lines.append(
            f"  project: {_fmt_diff_value(preview.from_project)} -> {_fmt_diff_value(preview.to_project)}"
        )
    return "\n".join(lines)


def format_config(config: object) -> str:
    lines = ["config:"]
    for f in fields(config):  # type: ignore[arg-type]
        lines.append(f"  {f.name}: {getattr(config, f.name)!r}")
    return "\n".join(lines)
