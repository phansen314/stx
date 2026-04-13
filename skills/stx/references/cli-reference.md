# stx CLI Reference

Full flag reference for the `stx` CLI. See `SKILL.md` for the core workflow.

---

## Global Flags

Apply to every command. Place before the subcommand:  `stx [global flags] <command> [flags]`

| Flag | Short | Default | Description |
|---|---|---|---|
| `--db PATH` | — | `~/.local/share/stx/stx.db` | Path to SQLite DB |
| `--workspace NAME` | `-w` | active-workspace file | Workspace name override (bypasses `~/.local/share/stx/active-workspace`) |
| `--json` | — | off | Force JSON output (also auto-enabled when stdout is a pipe) |
| `--text` | — | off | Force text output even when piped |
| `--quiet` | `-q` | off | Suppress success output (text mode only) |

**Output format auto-detection:** When stdout is a terminal, text is emitted. When stdout is piped or redirected, JSON is emitted automatically — no flag needed. `--json` and `--text` override the auto-detection and are mutually exclusive.

`--quiet` suppresses success text output only. It has **no effect in JSON mode** — JSON output is always emitted to stdout on success.

**JSON envelope:**
- Success → stdout: `{"ok": true, "data": ...}`
- Error → stderr: `{"ok": false, "error": "...", "code": "..."}`

See [`json-schema.md`](json-schema.md) for per-command `data` shapes.

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

## Archive Semantics

Archives are **soft-deletes** — rows are never removed from the database; the `archived` flag is set to `1`.

- **Visibility:** archived entities are hidden by default. Use `--archived include` or `--archived only` on `ls` commands where supported (`workspace ls`, `status ls`, `project ls`, `tag ls`, `group ls`, `task ls`).
- **No unarchive command.** There is no `unarchive` or `restore` subcommand. To restore an entity, use the SQLite CLI directly: `sqlite3 ~/.local/share/stx/stx.db "UPDATE tasks SET archived=0 WHERE id=N"`.
- **Cascade archive:** `workspace archive`, `project archive`, and `group archive` cascade to all descendants (statuses, tasks, groups, tags where applicable). See individual archive subcommand rows for cascade scope.

---

## Task Commands

### `stx task create <title> -S <status> [flags]`

`-S/--status` is **required** — there is no default status.

| Flag | Short | Default | Description |
|---|---|---|---|
| `--status` | `-S` | **required** | Target status name |
| `--desc` | `-d` | — | Description |
| `--project` | `-p` | — | Project name |
| `--priority` | — | `1` | Priority (free-form integer; interpretation is user-defined — use metadata for labeled schemes) |
| `--due` | — | — | Due date `YYYY-MM-DD` |
| `--tag` | `-t` | — | Tag name (repeatable) |
| `--group` | `-g` | — | Group title (infers project from group if `--project` not given) |

```sh
stx task create "Write README" -S "To Do"
stx task create "Deploy to prod" -S Backlog --project "Q2 launch" --priority 3 --due 2026-05-01
stx task create "Add tests" -S "To Do" --tag backend --tag ci
stx task create "Fix layout" -S "To Do" --group "Frontend" --project "Q2 launch"
```

The JSON response is a full `TaskDetail` (same shape as `stx task show`), including any tags attached via `--tag`.

---

### `stx task ls [flags]`

| Flag | Short | Default | Description |
|---|---|---|---|
| `--archived` | — | `hide` | Archived visibility: `hide` (default), `include` (active + archived), `only` (archived only) |
| `--status` | `-S` | — | Filter by status name |
| `--project` | `-p` | — | Filter by project name |
| `--priority` | — | — | Filter by priority integer |
| `--search` | — | — | Title substring search |
| `--group` | `-g` | — | Filter by group title |
| `--tag` | `-t` | — | Filter by tag name (single value; not repeatable — unlike `task create`/`task edit` which accept multiple `-t` flags) |

```sh
stx task ls
stx task ls --project "Q2 launch" --status "In Progress"
stx task ls --search auth --priority 3
stx task ls --tag backend --archived include
```

---

### `stx task show <task>`

Shows full task detail: description, history, edges (`edge_sources` / `edge_targets` each carrying a `kind`), group, tags. `<task>` accepts numeric IDs (`1`, `task-0001`, `#1`) or a title string.

```sh
stx task show task-0001
stx task show "Write README"
```

---

### `stx task edit <task_num> [flags]`

All flags are optional; only provided fields are updated.

| Flag | Short | Default | Description |
|---|---|---|---|
| `--title` | — | — | New title |
| `--desc` | `-d` | — | New description |
| `--priority` | — | — | New priority integer |
| `--due` | — | — | New due date `YYYY-MM-DD` |
| `--project` | `-p` | — | Change project |
| `--tag` | `-t` | — | Add tag (repeatable) |
| `--untag` | — | — | Remove tag (repeatable; errors if tag not currently on task) |
| `--dry-run` | — | off | Preview the field + tag diff without writing |

```sh
stx task edit task-0003 --priority 4 --due 2026-06-01
stx task edit task-0003 --tag urgent --untag backend
stx task edit task-0003 --priority 5 --dry-run
```

---

### `stx task mv <task> --status <status> [position] [flags]`

**Within-workspace only.** Use `stx task transfer` for cross-workspace moves.

| Arg/Flag | Description |
|---|---|
| `--status` / `-S` | Target status name (**required**) |
| `position` (optional positional) | Integer position within status (default: `0` = top) |
| `--project` / `-p` | Also change the task's project |
| `--dry-run` | Preview from/to status + position without writing |

```sh
stx task mv task-0001 --status "In Progress"
stx task mv task-0001 -S Done 2          # position 2 within Done status
stx task mv task-0001 -S Backlog --project "Next sprint"
stx task mv task-0001 -S Done --dry-run
```

**Note:** `stx task done` does not exist. To mark done: `stx task mv <task> -S Done` (requires a status literally named "Done").

---

### `stx task archive <task> [--force] [--dry-run]`

Archives the task (`archived=true`). Prompts for y/N confirmation unless `--force` is passed. `--dry-run` previews without executing. Non-interactive stdin (pipes, CI) requires `--force` or `--dry-run` — the command fails fast with an error rather than hang on `input()`. Archived tasks remain queryable via `task ls --archived include` or `--archived only`.

---

### `stx task log <task>`

Shows the full audit trail of field changes for a task. Entries come from the unified `journal` table (entity_type = 'task').

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

Text output for `ls` on an empty entity: `"no metadata"`. `get`/`set`/`del` on a missing key raise `LookupError` (`not_found`, exit 3).

Markdown export (`stx export --md`) renders metadata under dedicated sections: `**Metadata:**` block per workspace, `### Project Metadata`, `### Group Metadata`, `### Task Metadata`. JSON export (`stx export`) inlines `metadata` dicts on every entity.

---

### `stx task meta`

| Command | Args | Description |
|---|---|---|
| `task meta ls` | `task` | List all metadata entries; empty → `"no metadata"` |
| `task meta get` | `task key` | Get the value for a key |
| `task meta set` | `task key value` | Set (create or overwrite) a key's value |
| `task meta del` | `task key` | Remove a key |

`task` accepts numeric IDs or title strings — resolution is automatic. Metadata is also shown by `stx task show`. Cross-workspace `stx task transfer` copies task metadata verbatim to the new task.

```sh
stx task meta set task-0001 branch feat/kv
stx task meta set task-0001 jira PROJ-123
stx task meta set task-0001 BRANCH feat/kv-v2   # "BRANCH" normalizes to "branch"; overwrites
stx task meta ls task-0001
stx task meta get task-0001 branch
stx task meta del task-0001 jira
```

---

### `stx workspace meta`

Operates on the **active** workspace (or the workspace named by the global `-w/--workspace` flag). No positional name.

| Command | Args | Description |
|---|---|---|
| `workspace meta ls` | — | List metadata for the active workspace |
| `workspace meta get` | `key` | Get a value |
| `workspace meta set` | `key value` | Set or overwrite a value |
| `workspace meta del` | `key` | Remove a key |

```sh
stx workspace meta set env prod
stx workspace meta set region us-east-1
stx workspace meta ls
stx -w ops workspace meta get env     # -w targets a different workspace
```

---

### `stx project meta`

Positional project name is required (there is no "active project" concept).

| Command | Args | Description |
|---|---|---|
| `project meta ls` | `name` | List metadata for a project |
| `project meta get` | `name key` | Get a value |
| `project meta set` | `name key value` | Set or overwrite a value |
| `project meta del` | `name key` | Remove a key |

```sh
stx project meta set backend owner alice
stx project meta set backend slack "#backend-dev"
stx project meta ls backend
stx project meta del backend slack
```

---

### `stx group meta`

Positional group title + optional `--project/-p` for disambiguation when the title collides across projects in the same workspace.

| Command | Args | Flags | Description |
|---|---|---|---|
| `group meta ls` | `title` | `--project/-p` | List metadata for a group |
| `group meta get` | `title key` | `--project/-p` | Get a value |
| `group meta set` | `title key value` | `--project/-p` | Set or overwrite a value |
| `group meta del` | `title key` | `--project/-p` | Remove a key |

```sh
stx group meta set "Sprint 1" start 2026-01-01 --project backend
stx group meta set "Sprint 1" end 2026-01-14 --project backend
stx group meta ls "Sprint 1" --project backend
```

In `stx export --md` the Group Metadata section labels each block `#### <project> > <group>` to disambiguate.

---


## `stx task transfer` — Cross-Workspace Move

`stx task mv` is within-workspace only. `stx task transfer` handles cross-workspace moves.

**Behavior:**
1. Creates a copy of the task on the target workspace in the specified status
2. Archives the original task
3. **Fails** if the task has any active edges (incoming or outgoing) — archive them first with `stx edge archive --source … --target …`

| Flag | Short | Required | Description |
|---|---|---|---|
| `--to` | — | **yes** | Target workspace name |
| `--status` | `-S` | **yes** | Status on target workspace |
| `--project` | `-p` | no | Project on target workspace |
| `--dry-run` | — | no | Preview without executing; validates blocking edges |

```sh
stx task transfer task-0001 --to ops --status Backlog
stx task transfer task-0001 --to ops --status Backlog --project infra
stx task transfer task-0001 --to ops --status Backlog --dry-run
```

> **Workspace flag disambiguation:** The global `-w/--workspace` selects the **source** workspace (or falls back to the active workspace). The transfer subcommand's own `--to` selects the **target** workspace. Both may appear on the same command line.


---

## `stx workspace` Subcommands

| Command | Args | Flags | Description |
|---|---|---|---|
| `workspace create` | `name` | `--statuses "A,B,C"` | Create workspace; auto-switches active; optionally seed statuses. `--statuses` takes a single comma-separated string (e.g. `--statuses "To Do,In Progress,Done"`). Quote the whole value. |
| `workspace ls` | — | `--archived {hide,include,only}` (default `hide`) | List workspaces; marks active workspace |
| `workspace show` | `[name]` | — | Single-call workspace snapshot: statuses with task counts, tasks, projects, tags, groups. Designed as a one-shot startup view for AI sessions. Operates on named workspace, active workspace, or `-w` override. |
| `workspace use` | `name` | — | Switch active workspace |
| `workspace rename` | `old new` | — | Rename workspace from `old` to `new` |
| `workspace archive` | `[name]` | `--force`, `--dry-run` | Cascade-archive workspace and all descendants (projects, groups, statuses, tasks). Prompts y/N unless `--force`. Clears active pointer if archiving active workspace. |

```sh
stx workspace create work --statuses "To Do,In Progress,Done"
stx workspace use personal
stx workspace ls
stx workspace show
stx workspace show other-ws
stx --json workspace show
stx workspace rename "work" "work-q2"
stx workspace archive work --dry-run
stx workspace archive work --force
```

---

## `stx status` Subcommands

| Command | Args | Flags | Description |
|---|---|---|---|
| `status create` | `name` | — | Create a status on the active workspace |
| `status ls` | — | `--archived hide\|include\|only` | List statuses on active workspace; default hides archived |
| `status rename` | `old new` | — | Rename a status |
| `status order` | `status1 status2 ...` | — | Set the TUI display order for statuses on the active workspace (or `-w`). Writes `~/.config/stx/tui.toml`. Partial ordering allowed — unlisted statuses fall to the end. |
| `status archive` | `name` | `--reassign-to STATUS`, `--force`, `--dry-run` | Archive status. `--dry-run` previews without executing. `--reassign-to` moves tasks to another status before archiving. `--force` archives all tasks in the status instead. Neither flag triggers a confirmation prompt — `--reassign-to` and `--force` both proceed immediately (works from pipes and CI without `--force` being special-cased). Without either flag the service layer blocks on active tasks and exits with an error. |

```sh
stx status create "Blocked"
stx status order backlog "in progress" review done
stx status archive "Old Status" --dry-run
stx status archive "Old Status" --reassign-to "Backlog"
stx status archive "Old Status" --force
```

---

## `stx project` Subcommands

| Command | Args | Flags | Description |
|---|---|---|---|
| `project create` | `name` | `--desc` / `-d` | Create project |
| `project ls` | — | `--archived hide\|include\|only` | List projects; default hides archived |
| `project show` | `name` | — | Show project detail |
| `project edit` | `name` | `--desc` / `-d`, `--dry-run` | Edit project description; `--dry-run` previews the diff |
| `project rename` | `old new` | — | Rename project from `old` to `new` |
| `project archive` | `name` | `--force`, `--dry-run` | Cascade-archive project and all groups/tasks. Prompts y/N unless `--force`. |

---

## `stx edge` Subcommands

Edges are directional links between tasks with a free-form `kind` label and their own metadata blob. Flags are explicit: `--source X --target Y --kind blocks` means **X points to Y with kind `blocks`** (the prior-dependency convention). The PK is `(source_id, target_id)` — a second edge between the same pair is rejected regardless of kind. Self-loops are rejected by a DB CHECK. Multi-hop cycles are currently allowed (cycle detection is deferred pending blocking-kind semantics rework).

**Kind constraint:** lowercase `[a-z0-9_.-]+`, 1-64 characters. Enforced by the service layer's `_normalize_edge_kind` and a DB `CHECK (kind GLOB '[a-z0-9_.-]*' AND length(kind) BETWEEN 1 AND 64)`.

| Command | Args | Flags | Description |
|---|---|---|---|
| `edge create` | — | `--source TASK --target TASK --kind KIND` (all required) | Add an edge from source to target with the given kind. Re-adding an archived `(source, target)` pair clears its metadata blob and flips `archived = 0`. |
| `edge archive` | — | `--source TASK --target TASK` (both required) | Soft-archive the active edge. There is no unarchive surface — re-create via `edge create`. |
| `edge ls` | — | `--source TASK`, `--kind KIND` | List active edges on the active workspace, filtered by endpoint and/or kind. Both source and target must also be active (archived endpoints are hidden). |
| `edge meta ls` | — | `--source TASK --target TASK` | List all metadata on the edge. |
| `edge meta get` | `key` | `--source TASK --target TASK` | Read a single metadata value. |
| `edge meta set` | `key value` | `--source TASK --target TASK` | Write or overwrite a metadata value. Same charset/length rules as task metadata (lowercase key, `[a-z0-9_.-]+`, 64-char key cap, 500-char value cap). |
| `edge meta del` | `key` | `--source TASK --target TASK` | Remove a metadata key. |

```sh
stx edge create --source task-0003 --target task-0001 --kind blocks
stx edge ls
stx edge ls --kind blocks
stx edge ls --source task-0003
stx edge meta set --source task-0003 --target task-0001 rationale "depends on refactor"
stx edge meta ls --source task-0003 --target task-0001
stx edge archive --source task-0003 --target task-0001
```

---

## `stx tag` Subcommands

Tags are workspace-scoped. Many-to-many with tasks. `stx task create`/`stx task edit` auto-create tags that don't exist yet.

| Command | Args | Flags | Description |
|---|---|---|---|
| `tag create` | `name` | — | Create a tag (workspace-scoped) |
| `tag ls` | — | `--archived {hide,include,only}` (default `hide`) | List tags |
| `tag rename` | `old new` | — | Rename tag from `old` to `new` |
| `tag archive` | `name` | `--unassign`, `--force`, `--dry-run` | Archive tag; `--unassign` strips it from all tasks first. Prompts y/N unless `--force`. |

```sh
stx tag create backend
stx tag ls
stx tag archive backend --unassign
```

---

## `stx group` Subcommands

Groups are project-scoped hierarchical collections of tasks. All group commands accept `--project/-p` to scope to a project.

**Project flag asymmetry:** `group create` requires `--project` because groups cannot exist outside a project. `group ls` makes it optional — omit it to list every group in the workspace across all projects. This is intentional: creation demands the scope, listing is allowed to span it for convenience.

| Command | Args | Flags | Description |
|---|---|---|---|
| `group create` | `title` | `--project/-p` (**required**), `--parent TITLE`, `--desc/-d` | Create group; optionally nested under parent |
| `group ls` | — | `--project/-p`, `--archived {hide,include,only}` (default `hide`) | List groups (flat) |
| `group show` | `title` | `--project/-p` | Show detail with ancestry |
| `group rename` | `title new_title` | `--project/-p`, `--dry-run` | Rename; `--dry-run` previews the diff |
| `group edit` | `title` | `--desc/-d`, `--project/-p`, `--dry-run` | Edit group description; `--dry-run` previews the diff |
| `group archive` | `title` | `--project/-p`, `--force`, `--dry-run` | Cascade-archive group and all descendant groups/tasks. Prompts y/N unless `--force`. |
| `group mv` | `title` | `--parent TITLE` **or** `--to-top` (required), `--project/-p`, `--dry-run` | Reparent under another group, or `--to-top` to promote to top-level; `--dry-run` previews the diff |
| `group assign` | `task title` | `--project/-p` | Assign task to group |
| `group unassign` | `task` | — | Unassign task from its group |
| `group edge create` | — | `-s/--source TITLE --target TITLE --kind KIND` (all required), `--source-project`, `--target-project` | Add an edge between groups with the given kind. Project flags disambiguate when titles collide across projects or the edge is cross-project. |
| `group edge archive` | — | `-s/--source TITLE --target TITLE` (both required), `--source-project`, `--target-project` | Archive an active group edge. |
| `group edge ls` | — | `-s/--source TITLE`, `--kind KIND`, `--source-project` | List active group edges on the active workspace; optional source/kind filters. |
| `group edge meta ls\|get\|set\|del` | `[key [value]]` | `-s/--source TITLE --target TITLE --source-project --target-project` | Metadata CRUD on a single group edge. Same rules as task-edge metadata. |

```sh
stx group create "Backend" --project "API rewrite" --desc "Core API services"
stx group create "Auth" --project "API rewrite" --parent "Backend"
stx group assign task-0005 "Auth" --project "API rewrite"
stx group ls --project "API rewrite"
stx group mv "Auth" --parent "Frontend" --project "API rewrite"
stx group mv "Backend" --to-top --project "API rewrite"  # promote to top-level
stx group edge create --source "Sprint 2" --target "Sprint 1" --kind blocks --source-project backend --target-project backend
```

---

## `stx export`

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
stx export
stx export -o /tmp/workspace-snapshot.md
stx --json export
stx --json export -o /tmp/snapshot.md
```

---

## `stx info`

Read-only diagnostic. Lists the DB file, WAL/SHM sidecars, and active-workspace pointer — each with an existence marker. No flags.

```sh
stx info
stx --json info
```

JSON `data` shape: `{"db": {"path": "...", "exists": bool}, "wal": {...}, "shm": {...}, "active_workspace": {...}}`

---

## `stx backup <dest> [--overwrite]`

Atomic binary DB snapshot using SQLite's backup API. Safe to run before migrations.

```sh
stx backup /tmp/stx-backup.db
stx backup /tmp/stx-backup.db --overwrite
```

---

## `stx config` Subcommands

Manages TUI configuration stored in `~/.config/stx/tui.toml`. Only a subset of config fields are editable via CLI (see allowlist below); all fields are readable.

| Subcommand | Args | Description |
|---|---|---|
| `ls` | — | Show all config values. |
| `get <key>` | key | Print the value of a single config key. Accepts any key (not just editable ones). |
| `set <key> <value>` | key value | Set an editable config value. Writes to tui.toml immediately. Applies on next TUI launch. |
| `unset <key>` | key | Reset an editable config key to its dataclass default. |

**Editable keys:** `auto_refresh_seconds` (positive integer), `active_workspace` (workspace id or name).

`stx config set active_workspace <name>` is equivalent to `stx workspace use <name>` — both write `active_workspace` to `tui.toml`.

```
stx config ls
stx config get auto_refresh_seconds
stx config set auto_refresh_seconds 60
stx config set active_workspace myproject
stx config unset active_workspace
```

**Active workspace storage:** `active_workspace` is stored in `tui.toml`. A legacy `~/.local/share/stx/active-workspace` file is still read as a fallback for one release; writes no longer go there.

---

## `stx tui [--db PATH]`

Launches the Textual TUI interface. No JSON output. Useful for interactive exploration — not scripted workflows.

**Keybindings** (selected): `w` focus tree, `b` focus board, `e` edit selected entity, `m` edit metadata on selected entity (task/workspace/project/group), `n` new resource, `s` switch workspace, `[`/`]` move task across statuses, `r` refresh, `ctrl+q` quit. The metadata editor is reached by pressing `m` on a focused kanban task card or any entity node in the workspace tree; it presents editable key/value rows with add/delete buttons and atomically bulk-replaces the entity's metadata blob on save via `service.replace_*_metadata`. Keys are normalized to lowercase before comparison so retyping a key's case is a no-op.

Switching workspace via the left-panel tree is an in-session focus change only; it does not modify the active workspace persisted on disk. Use `stx workspace use` or `stx config set active_workspace` to change the terminal default.

---

## Task identifier resolution

Every task-referencing command auto-detects whether the argument is an ID or a title. Numeric forms (`1`, `task-0001`, `#1`, `0001`) are tried first; anything else is looked up as a title on the active workspace. A task whose title literally looks like `task-NNNN` would be resolved as an ID, not a title — avoid such titles.

---

## JSON `data` Shapes by Command

| Command | `data` shape |
|---|---|
| `task create` | full TaskDetail (with `status`, `project`, `group`, `tags`, `edge_sources`, `edge_targets`, `history`, `metadata`). `edge_sources`/`edge_targets` each is a list of `{task: Task, kind: str}`. |
| `task edit`, `task archive`, `task mv` | full TaskDetail (same shape as `task show`) |
| `task edit --dry-run`, `project edit --dry-run`, `group edit/rename/mv --dry-run` | `EntityUpdatePreview`: `{entity_type, entity_id, label, before, after, tags_added, tags_removed}` |
| `task mv --dry-run` | `TaskMovePreview`: `{task_id, title, from_status, to_status, from_position, to_position, from_project, to_project, project_changed}` |
| `workspace create/rename` | full Workspace object |
| `workspace archive` | `{"workspace": {...Workspace}, "active_cleared": bool}` — `active_cleared` is `true` when the archived workspace was the active workspace and the active-workspace pointer was cleared as a side-effect. **Note:** this is the only archive command that returns an envelope rather than a bare entity — the `active_cleared` field represents a CLI state side-effect that cannot be inferred from the workspace object alone. |
| `status create/rename/archive` | full Status object |
| `status order` | `{"workspace_id": N, "statuses": [{"id": N, "name": str}, ...]}` |
| `project create/archive` | full Project object |
| `tag create/archive` | full Tag object |
| `edge create/archive` | `{"source_id": N, "source_title": str, "target_id": N, "target_title": str, "kind": str}` |
| `edge ls` | array of **TaskEdgeListItem**: `[{"source_id": N, "source_title": str, "target_id": N, "target_title": str, "workspace_id": N, "kind": str}, ...]` |
| `edge meta ls` | `[{"key": str, "value": str}, ...]` (sorted; empty if no metadata) |
| `edge meta get/set/del` | `{"key": str, "value": str}` |
| `group edge create/archive` | `{"source_id": N, "source_title": str, "target_id": N, "target_title": str, "kind": str}` (group ids/titles) |
| `group edge ls` | array of **GroupEdgeListItem**, analogous to `edge ls` shape |
| `group edge meta ls\|get\|set\|del` | same shapes as task-edge metadata |
| `group assign` | full TaskDetail — hydrated `group` object includes `title` |
| `group unassign` | full TaskDetail |
| `task transfer` (live) | `{"task": {...TaskDetail}, "source_task_id": N}` |
| `task transfer --dry-run` | `{"task_id": N, "task_title": str, "source_workspace_id": N, "target_workspace_id": N, "target_status_id": N, "target_project_id": N\|null, "can_move": bool, "blocking_reason": str\|null, "edge_ids": [...], "is_archived": bool}` |
| `task ls` | `[{"status": {...Status}, "tasks": [{...TaskListItem}]}, ...]` — grouped by status, mirrors text output. Each element has a full Status object and a `tasks` array of TaskListItem objects (with pre-resolved `project_name`, `tag_names`). |
| `workspace ls` | array of Workspace objects with `"active": bool` field |
| `status ls` | array of Status objects |
| `project ls` | array of Project objects |
| `tag ls` | array of Tag objects |
| `group ls` | array of GroupRef objects with `project_name` denormalized (avoids extra round-trip) |
| `task show` | full TaskDetail (with `status`, `project`, `group`, `tags`, `edge_sources`, `edge_targets`, `history`, `metadata`) |
| `project show` | ProjectDetail with `tasks` array and `metadata` dict |
| `group show` | GroupDetail with `tasks`, `children` arrays, and `metadata` dict |
| `workspace ls` / `project ls` / `group ls` | entities include their `metadata` dicts |
| `task log` | array of TaskHistory objects |
| `workspace show` | `{"view": {"workspace": {...}, "statuses": [...]}, "projects": [...], "tags": [...], "groups": [...]}` |
| `export` | `{"markdown": "..."}` or `{"output_path": "...", "bytes": N}` when `-o FILE` |
| `backup` | `{"source": "...", "dest": "...", "bytes": N}` |
| `info` | `{"db": {"path": str, "exists": bool}, "wal": {...}, "shm": {...}, "active_workspace": {...}}` |
| `task meta ls`, `workspace meta ls`, `project meta ls`, `group meta ls` | `[{"key": "...", "value": "..."}]` (sorted; empty list if no metadata) |
| `task meta get/set/del`, `workspace meta get/set/del`, `project meta get/set/del`, `group meta get/set/del` | `{"key": "...", "value": "..."}` |
| `config ls` | full TuiConfig dict: `{theme, show_task_descriptions, show_archived, confirm_archive, default_priority, auto_refresh_seconds, active_workspace, status_order}` |
| `config get` | `{"key": str, "value": any}` |
| `config set`, `config unset` | `{"key": str, "value": any}` — value after write |

> **`task ls` vs `workspace show`:** `task ls --json` returns `[{status, tasks}]` — tasks grouped by status, matching the text output. `workspace show` returns the richer kanban context view (`{"view": {"workspace": {...}, "statuses": [...]}, "projects": [...], "tags": [...], "groups": [...]}`) for full workspace snapshot.
