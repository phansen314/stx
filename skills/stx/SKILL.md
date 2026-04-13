---
name: stx
description: Use when the user wants to persist structured context, a kanban board, or a multi-step plan across sessions via the local `stx` CLI — creating workspaces, managing nested groups, tracking tasks, moving statuses, querying workspace state, workflow tracking, or running `stx workspace show`/`stx export`. Not for ad-hoc in-chat task decomposition.
---

*If `stx` is not found, ask the user how they'd like to install it.*

## Core Workflow

1. **Pick or create a workspace.** Pass `--statuses` to seed statuses — otherwise the workspace starts empty and `stx task create` will fail. Override active workspace per-command with `-w/--workspace`:
   ```sh
   stx workspace create work --statuses "Backlog,In Progress,Done"
   ```

2. **Create tasks** — `-S/--status` is **required**, there is no default status:
   ```sh
   stx task create "Write README" -S Backlog
   ```

3. **Move tasks as work progresses** — the status must exist by name:
   ```sh
   stx task mv task-0001 -S "In Progress"
   ```

4. **Check workspace state** at any point:
   ```sh
   stx workspace show   # full snapshot: statuses, tasks, tags, groups
   stx task ls          # task list with filters (--status, --group, --tag, --search)
   ```

### Optional capabilities

- **Edges** — `stx edge create --source task-0003 --target task-0001 --kind blocks` links task-0003 to task-0001 with the `blocks` kind. `kind` is a free-form lowercase label (`[a-z0-9_.-]+`, 1-64 chars); `blocks` is the convention for prior dependency semantics, but any token is accepted. Each edge also carries its own metadata blob via `stx edge meta ls|get|set|del --source <t> --target <t>`.
- **Tags** — workspace-scoped, repeatable: `stx task create "..." -S Backlog --tag backend --tag ci`. Auto-created if missing.
- **Groups** — workspace-scoped hierarchies, nestable without depth limit: `stx group create "Sprint 1"`, then `stx group assign <task> <group>` (or pass `--group/-g` at task create time to skip the separate assign step). Groups can be nested: `stx group create "Sub-group" --parent "Sprint 1"`.
- **Group edges** — `stx group edge create --source <title> --target <title> --kind blocks` (titles resolved within the active workspace; pass `--source-parent`/`--target-parent` to disambiguate when titles collide). Mirror commands for `archive`, `ls`, and `meta *`.
- **Entity metadata** — arbitrary key/value pairs on any task, workspace, or group: `stx task meta set task-0001 branch feat/kv`, `stx workspace meta set region us-east-1`, `stx group meta set "Sprint 1" start 2026-01-01`. Keys are lowercase-normalized (`Branch` → `branch`), charset `[a-z0-9_.-]+`, max 64 chars. Values free-form up to 500 chars. Use for linking to external IDs (JIRA, GitHub, branches, PRs), environment tags, ownership, sprint windows, etc.
- **Cross-workspace move** — use `stx task transfer` (not `stx task mv`): `stx task transfer task-0001 --to ops --status Backlog`. Tags and metadata are carried over; group assignment is not.
- **Archive (soft-delete)** — `stx {task,group,workspace,status,tag} archive <id>`. Cascade-archives descendants where applicable. **Pass `--force` in scripts/loops** — archive commands prompt y/N interactively and fail-fast on non-interactive stdin. No unarchive command; restore via SQLite directly.
- **Audit trail** — `stx task log <task>` shows task field-change history. The underlying `journal` table covers all entity types (tasks, groups, workspaces, statuses, task/group edges) and per-key metadata diffs — queryable directly via `stx export` or SQLite.
- **Milestone snapshot** — `stx export` (all workspaces, Mermaid edge graphs labelled by `kind`); `-o FILE` writes to disk.

See `references/cli-reference.md` for full flag details, JSON envelope shapes, and error codes.
