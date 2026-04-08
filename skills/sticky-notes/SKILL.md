---
name: sticky-notes
description: Use when the user wants to persist a kanban board, todo list, or multi-step plan across sessions via the local `todo` CLI — creating workspaces, tracking tasks, moving statuses, querying workspace state, workflow tracking, or running `todo context`/`todo export`. Not for ad-hoc in-chat task decomposition.
---

*If `todo` is not found, ask the user how they'd like to install it.*

## Core Workflow

1. **Pick or create a workspace.** Pass `--statuses` to seed statuses — otherwise the workspace starts empty and `todo task create` will fail. Override active workspace per-command with `-w/--workspace`:
   ```sh
   todo workspace create work --statuses "Backlog,In Progress,Done"
   ```

2. **Create tasks** — `-S/--status` is **required**, there is no default status:
   ```sh
   todo task create "Write README" -S Backlog
   ```

3. **Move tasks as work progresses** — the status must exist by name:
   ```sh
   todo task mv task-0001 "In Progress"
   ```

4. **Check workspace state** at any point:
   ```sh
   todo context   # full snapshot: statuses, tasks, projects, tags, groups
   todo task ls   # task list with filters (--project, --status, --tag, --search)
   ```

### Optional capabilities

- **Projects** — group related tasks: `todo project create "Q2 launch"`, then pass `--project "Q2 launch"` to `todo task create`.
- **Dependencies** — `todo dep create task-0003 task-0001` means task-0003 is blocked by task-0001.
- **Tags** — workspace-scoped, repeatable: `todo task create "..." -S Backlog --tag backend --tag ci`. Auto-created if missing.
- **Groups** — project-scoped hierarchies: `todo group create "Sprint 1" --project "Q2 launch"` (`--project` is required), then `todo group assign <task> <group>`.
- **Group dependencies** — `todo group-dep create <group> <depends-on>` (by title within the same project).
- **Cross-workspace move** — use `todo task transfer` (not `todo task mv`): `todo task transfer task-0001 --workspace ops --status Backlog`.
- **Audit trail** — `todo task log <task>` shows full field-change history.
- **Milestone snapshot** — `todo export` (all workspaces, Mermaid dep graphs); `-o FILE` writes to disk.

See `references/cli-reference.md` for full flag details, JSON envelope shapes, and error codes.
