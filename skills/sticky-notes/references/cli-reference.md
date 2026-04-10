# sticky-notes CLI Reference

Full flag reference for the `todo` CLI. See `SKILL.md` for the core workflow.

---

## Global Flags

Apply to every command. Place before the subcommand:  `todo [global flags] <command> [flags]`

| Flag | Short | Default | Description |
|---|---|---|---|
| `--db PATH` | — | `~/.local/share/sticky-notes/sticky-notes.db` | Path to SQLite DB |
| `--workspace NAME` | `-w` | active-workspace file | Workspace name override (bypasses `~/.local/share/sticky-notes/active-workspace`) |
| `--json` | — | off | Emit JSON envelope instead of text |
| `--quiet` | `-q` | off | Suppress success output |

**JSON envelope:**
- Success → stdout: `{"ok": true, "data": ...}`
- Error → stderr: `{"ok": false, "error": "...", "code": "..."}`

**Exit codes:**

| code | meaning |
|---|---|
| `0` | success |
| `2` | SQLite / database error |
| `3` | `not_found` — entity doesn't exist |
| `4` | `validation` — bad argument value, duplicate names, integrity violations |
| `5` | `missing_active_workspace` — no active workspace set |
| `130` | interrupted (SIGINT) |

---

## Task Commands

### `todo task create <title> -S <status> [flags]`

`-S/--status` is **required** — there is no default status.

| Flag | Short | Default | Description |
|---|---|---|---|
| `--status` | `-S` | **required** | Target status name |
| `--desc` | `-d` | — | Description |
| `--project` | `-p` | — | Project name |
| `--priority` | — | `1` | Priority 1–5 (convention: 1=lowest; range only is enforced) |
| `--due` | — | — | Due date `YYYY-MM-DD` |
| `--tag` | `-t` | — | Tag name (repeatable) |
| `--group` | `-g` | — | Group title (infers project from group if `--project` not given) |

```sh
todo task create "Write README" -S "To Do"
todo task create "Deploy to prod" -S Backlog --project "Q2 launch" --priority 3 --due 2026-05-01
todo task create "Add tests" -S "To Do" --tag backend --tag ci
todo task create "Fix layout" -S "To Do" --group "Frontend" --project "Q2 launch"
```

The JSON response is a full `TaskDetail` (same shape as `todo task show`), including any tags attached via `--tag`.

---

### `todo task ls [flags]`

| Flag | Short | Default | Description |
|---|---|---|---|
| `--all` | `-a` | off | Include archived tasks |
| `--archived` | — | off | Show ONLY archived tasks |
| `--status` | `-S` | — | Filter by status name |
| `--project` | `-p` | — | Filter by project name |
| `--priority` | — | — | Filter by priority (1–5) |
| `--search` | — | — | Title substring search |
| `--group` | `-g` | — | Filter by group title |
| `--tag` | `-t` | — | Filter by tag name |

```sh
todo task ls
todo task ls --project "Q2 launch" --status "In Progress"
todo task ls --search auth --priority 3
todo task ls --tag backend --all
```

---

### `todo task show <task>`

Shows full task detail: description, history, dependencies, group, tags. `<task>` accepts numeric IDs (`1`, `task-0001`, `#1`) or a title string.

```sh
todo task show task-0001
todo task show "Write README"
```

---

### `todo task edit <task_num> [flags]`

All flags are optional; only provided fields are updated.

| Flag | Short | Default | Description |
|---|---|---|---|
| `--title` | — | — | New title |
| `--desc` | `-d` | — | New description |
| `--priority` | — | — | New priority (1–5) |
| `--due` | — | — | New due date `YYYY-MM-DD` |
| `--project` | `-p` | — | Change project |
| `--tag` | `-t` | — | Add tag (repeatable) |
| `--untag` | — | — | Remove tag (repeatable) |

```sh
todo task edit task-0003 --priority 4 --due 2026-06-01
todo task edit task-0003 --tag urgent --untag backend
```

---

### `todo task mv <task> --status <status> [position] [flags]`

**Within-workspace only.** Use `todo task transfer` for cross-workspace moves.

| Arg/Flag | Description |
|---|---|
| `--status` / `-S` | Target status name (**required**) |
| `position` (optional positional) | Integer position within status (default: `0` = top) |
| `--project` / `-p` | Also change the task's project |

```sh
todo task mv task-0001 --status "In Progress"
todo task mv task-0001 -S Done 2          # position 2 within Done status
todo task mv task-0001 -S Backlog --project "Next sprint"
```

**Note:** `todo task done` does not exist. To mark done: `todo task mv <task> -S Done` (requires a status literally named "Done").

---

### `todo task archive <task> [--force] [--dry-run]`

Archives the task (`archived=true`). Prompts for y/N confirmation unless `--force` is passed. `--dry-run` previews without executing. JSON mode (`--json`) auto-confirms. Non-interactive stdin (pipes, CI) requires `--force` or `--dry-run` — the command fails fast rather than hang on `input()`. Tasks remain queryable with `--all` or `--archived`.

---

### `todo task log <task>`

Shows the full audit trail of field changes (TaskHistory).

---

## Entity Metadata — `task meta` · `workspace meta` · `project meta` · `group meta`

Tasks, workspaces, projects, and groups each carry an independent JSON key/value metadata blob for arbitrary side data (external IDs, branch names, JIRA tickets, environment tags, sprint windows, ownership, etc.). The rules below apply to **all four** entity types — the per-entity subsections that follow only differ in how you identify the target entity.

**Key rules:** charset `[a-z0-9_.-]+` after lowercase-normalization, 1–64 characters. Keys are **case-insensitive** (normalized on write); `set X Branch` and `get X BRANCH` resolve to the same stored `branch` entry.

**Value rules:** free-form text, up to 500 characters.

**Uniform JSON `data` shape** across all four commands and all four entity types:

- `meta ls` → `[{"key": "...", "value": "..."}]` (sorted by key; empty list if no metadata)
- `meta get` → `{"key": "...", "value": "..."}`
- `meta set` → `{"key": "...", "value": "..."}` (the just-set record; key is the lowercase-normalized form)
- `meta del` → `{"key": "...", "value": "..."}` (the just-removed record)

Text output for `ls` on an empty entity: `"no metadata"`. `get`/`set`/`del` on a missing key raise `LookupError` (`not_found`, exit 1).

Markdown export (`todo export --md`) renders metadata under dedicated sections: `**Metadata:**` block per workspace, `### Project Metadata`, `### Group Metadata`, `### Task Metadata`. JSON export (`todo export`) inlines `metadata` dicts on every entity.

---

### `todo task meta`

| Command | Args | Description |
|---|---|---|
| `task meta ls` | `task_num` | List all metadata entries; empty → `"no metadata"` |
| `task meta get` | `task_num key` | Get the value for a key |
| `task meta set` | `task_num key value` | Set (create or overwrite) a key's value |
| `task meta del` | `task_num key` | Remove a key |

`task_num` accepts numeric IDs or title strings — resolution is automatic. Metadata is also shown by `todo task show`. Cross-workspace `todo task transfer` copies task metadata verbatim to the new task.

```sh
todo task meta set task-0001 branch feat/kv
todo task meta set task-0001 jira PROJ-123
todo task meta set task-0001 BRANCH feat/kv-v2   # "BRANCH" normalizes to "branch"; overwrites
todo task meta ls task-0001
todo task meta get task-0001 branch
todo task meta del task-0001 jira
```

---

### `todo workspace meta`

Operates on the **active** workspace (or the workspace named by the global `-w/--workspace` flag). No positional name.

| Command | Args | Description |
|---|---|---|
| `workspace meta ls` | — | List metadata for the active workspace |
| `workspace meta get` | `key` | Get a value |
| `workspace meta set` | `key value` | Set or overwrite a value |
| `workspace meta del` | `key` | Remove a key |

```sh
todo workspace meta set env prod
todo workspace meta set region us-east-1
todo workspace meta ls
todo -w ops workspace meta get env     # -w targets a different workspace
```

---

### `todo project meta`

Positional project name is required (there is no "active project" concept).

| Command | Args | Description |
|---|---|---|
| `project meta ls` | `name` | List metadata for a project |
| `project meta get` | `name key` | Get a value |
| `project meta set` | `name key value` | Set or overwrite a value |
| `project meta del` | `name key` | Remove a key |

```sh
todo project meta set backend owner alice
todo project meta set backend slack "#backend-dev"
todo project meta ls backend
todo project meta del backend slack
```

---

### `todo group meta`

Positional group title + optional `--project/-p` for disambiguation when the title collides across projects in the same workspace.

| Command | Args | Flags | Description |
|---|---|---|---|
| `group meta ls` | `title` | `--project/-p` | List metadata for a group |
| `group meta get` | `title key` | `--project/-p` | Get a value |
| `group meta set` | `title key value` | `--project/-p` | Set or overwrite a value |
| `group meta del` | `title key` | `--project/-p` | Remove a key |

```sh
todo group meta set "Sprint 1" start 2026-01-01 --project backend
todo group meta set "Sprint 1" end 2026-01-14 --project backend
todo group meta ls "Sprint 1" --project backend
```

In `todo export --md` the Group Metadata section labels each block `#### <project> > <group>` to disambiguate.

---

### `todo context`

Single-call workspace snapshot. No arguments. Outputs: statuses with task counts, tasks, projects, tags, groups. Designed as a one-shot startup view for AI sessions.

```sh
todo context
todo --json context
```

---

## `todo task transfer` — Cross-Workspace Move

`todo task mv` is within-workspace only. `todo task transfer` handles cross-workspace moves.

**Behavior:**
1. Creates a copy of the task on the target workspace in the specified status
2. Archives the original task
3. **Fails** if the task has any dependencies (incoming or outgoing) — archive them first with `todo dep archive`

| Flag | Short | Required | Description |
|---|---|---|---|
| `--to` | — | **yes** | Target workspace name |
| `--status` | `-S` | **yes** | Status on target workspace |
| `--project` | `-p` | no | Project on target workspace |
| `--dry-run` | — | no | Preview without executing; validates blocking deps |

```sh
todo task transfer task-0001 --to ops --status Backlog
todo task transfer task-0001 --to ops --status Backlog --project infra
todo task transfer task-0001 --to ops --status Backlog --dry-run
```

> **Workspace flag disambiguation:** The global `-w/--workspace` selects the **source** workspace (or falls back to the active workspace). The transfer subcommand's own `--to` selects the **target** workspace. Both may appear on the same command line.


---

## `todo workspace` Subcommands

| Command | Args | Flags | Description |
|---|---|---|---|
| `workspace create` | `name` | `--statuses "A,B,C"` | Create workspace; auto-switches active; optionally seed statuses. `--statuses` takes a single comma-separated string (e.g. `--statuses "To Do,In Progress,Done"`). Quote the whole value. |
| `workspace ls` | — | `--all` / `-a` | List all workspaces; marks active workspace |
| `workspace use` | `name` | — | Switch active workspace |
| `workspace rename` | `old new` | — | Rename workspace from `old` to `new` |
| `workspace archive` | `[name]` | `--force`, `--dry-run` | Cascade-archive workspace and all descendants (projects, groups, statuses, tasks). Prompts y/N unless `--force`. Clears active pointer if archiving active workspace. |

```sh
todo workspace create work --statuses "To Do,In Progress,Done"
todo workspace use personal
todo workspace ls
todo workspace rename "work" "work-q2"
todo workspace archive work --dry-run
todo workspace archive work --force
```

---

## `todo status` Subcommands

| Command | Args | Flags | Description |
|---|---|---|---|
| `status create` | `name` | — | Create a status on the active workspace |
| `status ls` | — | — | List statuses on active workspace |
| `status rename` | `old new` | — | Rename a status |
| `status order` | `workspace status1 status2 ...` | — | Set the TUI display order for statuses on a workspace. Writes `~/.config/sticky-notes/tui.toml`. Partial ordering allowed — unlisted statuses fall to the end. |
| `status archive` | `name` | `--reassign-to STATUS`, `--force` | Archive status; either reassign its tasks to another status, or `--force` to archive all tasks |

```sh
todo status create "Blocked"
todo status order dev backlog "in progress" review done
todo status archive "Old Status" --reassign-to "Backlog"
todo status archive "Old Status" --force
```

---

## `todo project` Subcommands

| Command | Args | Flags | Description |
|---|---|---|---|
| `project create` | `name` | `--desc` / `-d` | Create project |
| `project ls` | — | — | List projects |
| `project show` | `name` | — | Show project detail |
| `project edit` | `name` | `--desc` / `-d` | Edit project description |
| `project rename` | `old new` | — | Rename project from `old` to `new` |
| `project archive` | `name` | `--force`, `--dry-run` | Cascade-archive project and all groups/tasks. Prompts y/N unless `--force`. |

---

## `todo dep` Subcommands

Flags are explicit about direction: `--task X --blocked-by Y` means **X is blocked by Y**. No `dep ls` — use `todo task show <task>` to see `blocked_by` and `blocks` arrays.

| Command | Flags | Description |
|---|---|---|
| `dep create` | `--task TASK --blocked-by TASK` (both required) | Add dependency |
| `dep archive` | `--task TASK --blocked-by TASK` (both required) | Archive dependency (soft-delete) |

```sh
todo dep create --task task-0003 --blocked-by task-0001   # task-0003 is blocked by task-0001
todo dep archive --task task-0003 --blocked-by task-0001
```

---


## `todo tag` Subcommands

Tags are workspace-scoped. Many-to-many with tasks. `todo task create`/`todo task edit` auto-create tags that don't exist yet.

| Command | Args | Flags | Description |
|---|---|---|---|
| `tag create` | `name` | — | Create a tag (workspace-scoped) |
| `tag ls` | — | `--all` / `-a` | List tags (include archived with `-a`) |
| `tag rename` | `old new` | — | Rename tag from `old` to `new` |
| `tag archive` | `name` | `--unassign`, `--force`, `--dry-run` | Archive tag; `--unassign` strips it from all tasks first. Prompts y/N unless `--force`. |

```sh
todo tag create backend
todo tag ls
todo tag archive backend --unassign
```

---

## `todo group` Subcommands

Groups are project-scoped hierarchical collections of tasks. All group commands accept `--project/-p` to scope to a project.

**Project flag asymmetry:** `group create` requires `--project` because groups cannot exist outside a project. `group ls` makes it optional — omit it to list every group in the workspace across all projects. This is intentional: creation demands the scope, listing is allowed to span it for convenience.

| Command | Args | Flags | Description |
|---|---|---|---|
| `group create` | `title` | `--project/-p` (**required**), `--parent TITLE`, `--desc/-d` | Create group; optionally nested under parent |
| `group ls` | — | `--project/-p`, `--all/-a`, `--tree` | List (flat or tree view) |
| `group show` | `title` | `--project/-p` | Show detail with ancestry |
| `group rename` | `title new_title` | `--project/-p` | Rename |
| `group edit` | `title` | `--desc/-d`, `--project/-p` | Edit group description |
| `group archive` | `title` | `--project/-p`, `--force`, `--dry-run` | Cascade-archive group and all descendant groups/tasks. Prompts y/N unless `--force`. |
| `group mv` | `title` | `--parent TITLE` **or** `--to-top` (required), `--project/-p` | Reparent under another group, or `--to-top` to promote to top-level |
| `group assign` | `task group_title` | `--project/-p` | Assign task to group |
| `group unassign` | `task` | — | Unassign task from its group |
| `group dep create` | `group_title depends_on_title` | `--project/-p` | Add group dependency (group blocked by depends-on) |
| `group dep archive` | `group_title depends_on_title` | `--project/-p` | Archive group dependency (soft-delete) |

```sh
todo group create "Backend" --project "API rewrite" --desc "Core API services"
todo group create "Auth" --project "API rewrite" --parent "Backend"
todo group assign task-0005 "Auth" --project "API rewrite"
todo group ls --project "API rewrite" --tree
todo group mv "Auth" --parent "Frontend" --project "API rewrite"
todo group mv "Backend" --to-top --project "API rewrite"  # promote to top-level
todo group dep create "Sprint 2" "Sprint 1"   # Sprint 2 blocked by Sprint 1
```

---

## `todo export`

Exports the **entire database**. Default format is JSON; pass `--md` for Markdown with Mermaid dependency graphs.

| Flag | Short | Description |
|---|---|---|
| `--md` | — | Export as Markdown instead of JSON |
| `--output` | `-o` | Write to file instead of stdout (creates parent dirs) |
| `--overwrite` | — | Overwrite destination file if it already exists (required when `-o` points at an existing file) |

With `--json`:
- stdout (no `-o`): `{"markdown": "..."}`
- file (`-o`): `{"output_path": "...", "bytes": N}`

```sh
todo export
todo export -o /tmp/workspace-snapshot.md
todo --json export
todo --json export -o /tmp/snapshot.md
```

---

## `todo info`

Read-only diagnostic. Lists the DB file, WAL/SHM sidecars, and active-workspace pointer — each with an existence marker. No flags.

```sh
todo info
todo --json info
```

JSON `data` shape: `{"db": "...", "wal": "...", "shm": "...", "active_workspace": "...", "existing": [...]}`

---

## `todo backup <dest> [--overwrite]`

Atomic binary DB snapshot using SQLite's backup API. Safe to run before migrations.

```sh
todo backup /tmp/sticky-notes-backup.db
todo backup /tmp/sticky-notes-backup.db --overwrite
```

---

## `todo tui [--db PATH]`

Launches the Textual TUI interface. No JSON output. Useful for interactive exploration — not scripted workflows.

**Keybindings** (selected): `w` focus tree, `b` focus board, `e` edit selected entity, `m` edit metadata on selected entity (task/workspace/project/group), `n` new resource, `s` switch workspace, `[`/`]` move task across statuses, `r` refresh, `ctrl+q` quit. The metadata editor is reached by pressing `m` on a focused kanban task card or any entity node in the workspace tree; it presents editable key/value rows with add/delete buttons and atomically bulk-replaces the entity's metadata blob on save via `service.replace_*_metadata`. Keys are normalized to lowercase before comparison so retyping a key's case is a no-op.

---

## Task identifier resolution

Every task-referencing command auto-detects whether the argument is an ID or a title. Numeric forms (`1`, `task-0001`, `#1`, `0001`) are tried first; anything else is looked up as a title on the active workspace. A task whose title literally looks like `task-NNNN` would be resolved as an ID, not a title — avoid such titles.

---

## JSON `data` Shapes by Command

| Command | `data` shape |
|---|---|
| `task create` | full TaskDetail (with `status`, `project`, `group`, `tags`, `blocked_by`, `blocks`, `history`, `metadata`) |
| `task edit`, `task archive`, `task mv` | full Task object |
| `workspace create/rename/archive` | full Workspace object |
| `status create/rename/archive` | full Status object |
| `project create/archive` | full Project object |
| `tag create/archive` | full Tag object |
| `dep create/archive` | `{"task_id": N, "depends_on_id": N}` |
| `group-dep create/archive` | `{"group_id": N, "depends_on_id": N}` |
| `group assign` | `{"task": {...}, "group_id": N}` — `group_id` is duplicated: it appears here AND inside `task.group_id` (always equal after assign) |
| `group unassign` | full Task object |
| `task transfer` (live) | `{"task": {...}, "source_task_id": N}` |
| `task transfer --dry-run` | `{"task_id": N, "task_title": str, "source_workspace_id": N, "target_workspace_id": N, "target_status_id": N, "can_move": bool, "blocking_reason": str\|null, "dependency_ids": [...], "is_archived": bool}` — note: does NOT include `target_project_id` even when `--project` is passed |
| `task ls` | `{"workspace": {...}, "statuses": [{"status": {...}, "tasks": [...]}]}` |
| `workspace ls` | array of Workspace objects with `"active": bool` field |
| `status ls` | array of Status objects |
| `project ls` | array of Project objects |
| `tag ls` | array of Tag objects |
| `group ls` | array of GroupRef objects |
| `task show` | full TaskDetail (with `status`, `project`, `group`, `tags`, `blocked_by`, `blocks`, `history`, `metadata`) |
| `project show` | ProjectDetail with `tasks` array and `metadata` dict |
| `group show` | GroupDetail with `tasks`, `children` arrays, and `metadata` dict |
| `workspace ls` / `project ls` / `group ls` | entities include their `metadata` dicts |
| `task log` | array of TaskHistory objects |
| `context` | `{"view": {"workspace": {...}, "statuses": [...]}, "projects": [...], "tags": [...], "groups": [...]}` |
| `export` | `{"markdown": "..."}` or `{"output_path": "...", "bytes": N}` when `-o FILE` |
| `backup` | `{"source": "...", "dest": "...", "bytes": N}` |
| `info` | `{"db": "...", "wal": "...", "shm": "...", "active_workspace": "...", "existing": [...]}` |
| `task meta ls`, `workspace meta ls`, `project meta ls`, `group meta ls` | `[{"key": "...", "value": "..."}]` (sorted; empty list if no metadata) |
| `task meta get/set/del`, `workspace meta get/set/del`, `project meta get/set/del`, `group meta get/set/del` | `{"key": "...", "value": "..."}` |

> **`context` vs `ls` shape asymmetry:** `ls` returns `{"workspace": {...}, "statuses": [...]}` directly at the top level. `context` wraps the same workspace+statuses shape inside a `"view"` key — they are **not** interchangeable payloads.
