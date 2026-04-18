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
   stx workspace show   # full snapshot: statuses, tasks, groups
   stx task ls          # task list with filters (--status, --group, --search)
   ```

### Optional capabilities

- **Polymorphic edges** — `stx edge create --source task-0003 --target task-0001 --kind blocks` links task-0003 to task-0001 with the `blocks` kind. Endpoint type is inferred from path delimiters: `/A` or `/A/B/C` (leading slash) → group, `A/B/C` (multi-seg) → group, `A:leaf` / `:leaf` (contains `:`) → task, `task-NNNN`/`#N`/int → task by id, bare title → task. The leading-slash anchor lets you reference a root group as `/A` without needing the `group:` prefix. Explicit prefixes `group:`, `task:`, `workspace:`, `status:` override inference. Cross-type edges work (e.g. `--source /A/B/C --target D:task0` is group→task with no prefixes needed). `kind` is a free-form lowercase label (`[a-z0-9_.-]+`, 1-64 chars). Each edge carries a metadata blob via `stx edge meta ls|get|set|del --source <ref> --target <ref> --kind <k>` and an `acyclic` flag (default on for `blocks`/`spawns`).
- **Groups** — workspace-scoped hierarchies, nestable without depth limit: `stx group create "Sprint 1"`, then `stx group assign <task> <group>` (or pass `--group/-g` at task create time to skip the separate assign step). Nest via `--parent` or path-as-title: `stx group create "Sprint 1/Sub-group"`. Reference any group by path: `stx group show "Sprint 1/Sub-group"`. `/` and `:` are reserved for path syntax and forbidden in group/task titles.
- **Entity metadata** — arbitrary key/value pairs on any task, workspace, or group: `stx task meta set task-0001 branch feat/kv`, `stx workspace meta set region us-east-1`, `stx group meta set "Sprint 1" start 2026-01-01`. Keys are lowercase-normalized (`Branch` → `branch`), charset `[a-z0-9_.-]+`, max 64 chars. Values free-form up to 500 chars. Use for linking to external IDs (JIRA, GitHub, branches, PRs), environment tags, ownership, sprint windows, etc.
- **Cross-workspace move** — use `stx task transfer` (not `stx task mv`): `stx task transfer task-0001 --to ops --status Backlog`. Metadata is carried over; group assignment is not.
- **Archive (soft-delete)** — `stx {task,group,workspace,status} archive <id>`. Cascade-archives descendants where applicable. **Pass `--force` in scripts/loops** — archive commands prompt y/N interactively and fail-fast on non-interactive stdin. No unarchive command; restore via SQLite directly.
- **Audit trail** — `stx task log <task>` shows task field-change history. The underlying `journal` table covers all entity types (tasks, groups, workspaces, statuses, edges) and per-key metadata diffs — queryable directly via `stx export` or SQLite.
- **Done flags and terminal statuses** — `stx task done <task>` marks a task done independent of its status (no-op if already done). `stx task undone <task> [--force]` clears it (gated: requires `--force` in non-interactive stdin). Mark a status terminal via `stx status edit <name> --terminal`; tasks moved into (or created in) a terminal status auto-set `done=true`. The `done` flag is sticky — status moves do not clear it. `group.done` is a read-only derived field: true iff every non-archived child task and subgroup is done.
- **Next-task computation** — `stx next [--rank] [--include-blocked] [--limit N] [--edge-kind KIND]` topo-sorts the active acyclic `blocks` DAG (or any edge kind you specify) to surface the actionable **Ready** frontier and the **Blocked** list with pending blocker task IDs. Group endpoints are expanded to member tasks, so a `group-A blocks group-B` edge means all of A's tasks must finish before any of B's become ready. Use `--rank` to order by priority/due-date for agent task selection.
- **Graph visualization** — `stx graph` generates a DOT or Mermaid file from workspace edges. Use `--format mermaid` for Mermaid, `-k KIND` (repeatable) to filter by edge kind, `-o PATH` for explicit output. Default: DOT to a temp file.
- **Milestone snapshot** — `stx export` (all workspaces, Mermaid edge graphs labelled by `kind`); `-o FILE` writes to disk.
- **Event hooks** — post-only observers that fire after every entity mutation (fire-and-forget; write always proceeds). Config: `~/.config/stx/hooks.toml`. Inspect via `stx hook events|ls|validate|schema`. For authoring custom hooks interactively, invoke the `stx:hooks` skill (`skills/hooks/SKILL.md`). Full event catalog and recipe library in `references/hooks.md`.

See `references/cli-reference.md` for full flag details, JSON envelope shapes, and error codes.
