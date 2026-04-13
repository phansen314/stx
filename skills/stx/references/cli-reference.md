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

- **Visibility:** archived entities are hidden by default. Use `--archived include` or `--archived only` on `ls` commands where supported (`workspace ls`, `status ls`, `group ls`, `task ls`).
- **No unarchive command.** There is no `unarchive` or `restore` subcommand. To restore an entity, use the SQLite CLI directly: `sqlite3 ~/.local/share/stx/stx.db "UPDATE tasks SET archived=0 WHERE id=N"`.
- **Cascade archive:** `workspace archive` and `group archive` cascade to all descendants (statuses, tasks, groups where applicable). See individual archive subcommand rows for cascade scope.

---

## Task Commands

### `stx task create <title> -S <status> [flags]`

`-S/--status` is **required** — there is no default status.

| Flag | Short | Default | Description |
|---|---|---|---|
| `--status` | `-S` | **required** | Target status name |
| `--desc` | `-d` | — | Description |
| `--priority` | — | `1` | Priority (free-form integer; interpretation is user-defined — use metadata for labeled schemes) |
| `--due` | — | — | Due date `YYYY-MM-DD` |
| `--group` | `-g` | — | Group title |

```sh
stx task create "Write README" -S "To Do"
stx task create "Deploy to prod" -S Backlog --priority 3 --due 2026-05-01
stx task create "Fix layout" -S "To Do" --group "Frontend"
```

The JSON response is a full `TaskDetail` (same shape as `stx task show`).

---

### `stx task ls [flags]`

| Flag | Short | Default | Description |
|---|---|---|---|
| `--archived` | — | `hide` | Archived visibility: `hide` (default), `include` (active + archived), `only` (archived only) |
| `--status` | `-S` | — | Filter by status name |
| `--priority` | — | — | Filter by priority integer |
| `--search` | — | — | Title substring search |
| `--group` | `-g` | — | Filter by group title |

```sh
stx task ls
stx task ls --group "Sprint 1" --status "In Progress"
stx task ls --search auth --priority 3
stx task ls --archived include
```

---

### `stx task show <task>`

Shows full task detail: description, history, edges (`edge_sources` / `edge_targets` each carrying a `kind`), group. `<task>` accepts numeric IDs (`1`, `task-0001`, `#1`) or a title string.

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
| `--dry-run` | — | off | Preview the field diff without writing |

```sh
stx task edit task-0003 --priority 4 --due 2026-06-01
stx task edit task-0003 --priority 5 --dry-run
```

---

### `stx task mv <task> --status <status> [position] [flags]`

**Within-workspace only.** Use `stx task transfer` for cross-workspace moves.

| Arg/Flag | Description |
|---|---|
| `--status` / `-S` | Target status name (**required**) |
| `position` (optional positional) | Integer position within status (default: `0` = top) |
| `--dry-run` | Preview from/to status + position without writing |

```sh
stx task mv task-0001 --status "In Progress"
stx task mv task-0001 -S Done 2          # position 2 within Done status
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

## Entity Metadata — `task meta` · `workspace meta` · `group meta`

Tasks, workspaces, and groups each carry an independent JSON key/value metadata blob for arbitrary side data (external IDs, branch names, JIRA tickets, environment tags, sprint windows, ownership, etc.). The rules below apply to **all three** entity types — the per-entity subsections that follow only differ in how you identify the target entity.

**Key rules:** charset `[a-z0-9_.-]+` after lowercase-normalization, 1–64 characters. Keys are **case-insensitive** (normalized on write); `set X Branch` and `get X BRANCH` resolve to the same stored `branch` entry.

**Value rules:** free-form text, up to 500 characters.

**Uniform JSON `data` shape** across all four commands and all four entity types:

- `meta ls` → `[{"key": "...", "value": "..."}]` (sorted by key; empty list if no metadata)
- `meta get` → `{"key": "...", "value": "..."}`
- `meta set` → `{"key": "...", "value": "..."}` (the just-set record; key is the lowercase-normalized form)
- `meta del` → `{"key": "...", "value": "..."}` (the just-removed record)

Text output for `ls` on an empty entity: `"no metadata"`. `get`/`set`/`del` on a missing key raise `LookupError` (`not_found`, exit 3).

Markdown export (`stx export --md`) renders metadata under dedicated sections: `**Metadata:**` block per workspace, `### Group Metadata`, `### Task Metadata`. JSON export (`stx export`) inlines `metadata` dicts on every entity.

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

### `stx group meta`

Positional group title identifies the group within the active workspace.

| Command | Args | Description |
|---|---|---|
| `group meta ls` | `title` | List metadata for a group |
| `group meta get` | `title key` | Get a value |
| `group meta set` | `title key value` | Set or overwrite a value |
| `group meta del` | `title key` | Remove a key |

```sh
stx group meta set "Sprint 1" start 2026-01-01
stx group meta set "Sprint 1" end 2026-01-14
stx group meta ls "Sprint 1"
```

In `stx export --md` the Group Metadata section labels each block `#### <group title>`.

---


## `stx task transfer` — Cross-Workspace Move

`stx task mv` is within-workspace only. `stx task transfer` handles cross-workspace moves.

**Behavior:**
1. Creates a copy of the task on the target workspace in the specified status
2. Archives the original task
3. **Fails** if the task has any active edges (incoming or outgoing) — archive them first with `stx edge archive --source … --target …`

Metadata is carried over; group assignment is not.

| Flag | Short | Required | Description |
|---|---|---|---|
| `--to` | — | **yes** | Target workspace name |
| `--status` | `-S` | **yes** | Status on target workspace |
| `--dry-run` | — | no | Preview without executing; validates blocking edges |

```sh
stx task transfer task-0001 --to ops --status Backlog
stx task transfer task-0001 --to ops --status Backlog --dry-run
```

> **Workspace flag disambiguation:** The global `-w/--workspace` selects the **source** workspace (or falls back to the active workspace). The transfer subcommand's own `--to` selects the **target** workspace. Both may appear on the same command line.


---

## `stx workspace` Subcommands

| Command | Args | Flags | Description |
|---|---|---|---|
| `workspace create` | `name` | `--statuses "A,B,C"` | Create workspace; auto-switches active; optionally seed statuses. `--statuses` takes a single comma-separated string (e.g. `--statuses "To Do,In Progress,Done"`). Quote the whole value. |
| `workspace ls` | — | `--archived {hide,include,only}` (default `hide`) | List workspaces; marks active workspace |
| `workspace show` | `[name]` | — | Single-call workspace snapshot: statuses with task counts, tasks, groups. Designed as a one-shot startup view for AI sessions. Operates on named workspace, active workspace, or `-w` override. |
| `workspace use` | `name` | — | Switch active workspace |
| `workspace edit` | — | `--name NEW`, `--dry-run` | Edit active workspace (or `-w` override). `--name` renames it; `--dry-run` previews the diff. |
| `workspace log` | — | — | Show journal / change history for the active workspace. |
| `workspace archive` | `[name]` | `--force`, `--dry-run` | Cascade-archive workspace and all descendants (groups, statuses, tasks). Prompts y/N unless `--force`. Clears active pointer if archiving active workspace. |

```sh
stx workspace create work --statuses "To Do,In Progress,Done"
stx workspace use personal
stx workspace ls
stx workspace show
stx workspace show other-ws
stx --json workspace show
stx -w work workspace edit --name "work-q2"
stx workspace archive work --dry-run
stx workspace archive work --force
```

---

## `stx status` Subcommands

| Command | Args | Flags | Description |
|---|---|---|---|
| `status create` | `name` | — | Create a status on the active workspace |
| `status ls` | — | `--archived hide\|include\|only` | List statuses on active workspace; default hides archived |
| `status show` | `name` | — | Show status detail (including task count) |
| `status edit` | `name` | `--name NEW` | Edit status (rename via `--name`) |
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

## `stx edge` Subcommands

Edges are polymorphic directional links with a free-form `kind` label and their own metadata blob. Endpoints are typed refs: `task-NNNN` / `#NNNN` / `<task title>` for tasks, `group:<title>` for groups, `workspace:<name>` for workspaces. Cross-type edges are allowed (task→group, group→workspace, etc.). Flags are explicit: `--source X --target Y --kind blocks` means **X points to Y with kind `blocks`**. The PK is `(from_type, from_id, to_type, to_id, kind)` — multiple kinds between the same node pair coexist; re-adding the same `(source, target, kind)` tuple clears the metadata blob and flips `archived = 0`. Self-loops are rejected by a DB CHECK. Cross-workspace edges are rejected at the service layer.

**Kind constraint:** lowercase `[a-z0-9_.-]+`, 1-64 characters. Enforced by the service layer's `_normalize_edge_kind` and a DB `CHECK (kind GLOB '[a-z0-9_.-]*' AND length(kind) BETWEEN 1 AND 64)`.

**Acyclic flag:** each edge carries `acyclic` (default: `1` for `kind in {blocks, spawns}`, `0` otherwise). Cycle detection runs over the union of active acyclic edges — so mixing `blocks` and `spawns` in a cycle is rejected, but `informs` / `references` / `related-to` can freely form cycles. Override with `--acyclic` / `--no-acyclic`.

**Group disambiguation:** when multiple groups share a title under different parents, pass `--source-parent <parent-title>` / `--target-parent <parent-title>` on the create/archive/meta/ls surface.

| Command | Args | Flags | Description |
|---|---|---|---|
| `edge create` | — | `--source REF --target REF --kind KIND` (all required), `--source-parent`, `--target-parent`, `--acyclic`/`--no-acyclic` | Add an edge from source to target with the given kind. |
| `edge archive` | — | `--source REF --target REF --kind KIND` (all required), `--source-parent`, `--target-parent` | Soft-archive the active edge. Re-create via `edge create`. |
| `edge ls` | — | `--source REF`, `--target REF`, `--kind KIND`, `--source-parent`, `--target-parent` | List active edges on the active workspace; filters are optional. Both endpoints must be active (archived endpoints are hidden). |
| `edge meta ls` | — | `--source REF --target REF --kind KIND` | List all metadata on the edge. |
| `edge meta get` | `key` | `--source REF --target REF --kind KIND` | Read a single metadata value. |
| `edge meta set` | `key value` | `--source REF --target REF --kind KIND` | Write or overwrite a metadata value. Same charset/length rules as entity metadata (lowercase key, `[a-z0-9_.-]+`, 64-char key cap, 500-char value cap). |
| `edge meta del` | `key` | `--source REF --target REF --kind KIND` | Remove a metadata key. |

```sh
stx edge create --source task-0003 --target task-0001 --kind blocks
stx edge create --source task-0002 --target "group:Auth" --kind informs
stx edge ls
stx edge ls --kind blocks
stx edge ls --source task-0003
stx edge meta set --source task-0003 --target task-0001 --kind blocks rationale "depends on refactor"
stx edge meta ls --source task-0003 --target task-0001 --kind blocks
stx edge archive --source task-0003 --target task-0001 --kind blocks
```

---

## `stx group` Subcommands

Groups are workspace-scoped hierarchical collections of tasks. Root groups have no parent (`parent_id IS NULL`); nested groups specify `--parent`. All group commands resolve the group title within the active workspace (or `-w`).

| Command | Args | Flags | Description |
|---|---|---|---|
| `group create` | `title` | `--parent TITLE`, `--desc/-d` | Create group; optionally nested under a parent group |
| `group ls` | — | `--archived {hide,include,only}` (default `hide`) | List groups (flat, root-level by default) |
| `group show` | `title` | — | Show detail with ancestry |
| `group edit` | `title` | `--title NEW`, `--desc/-d`, `--dry-run` | Edit group fields; `--title` renames the group; `--dry-run` previews the diff |
| `group log` | `title` | — | Show journal / change history for the group. |
| `group archive` | `title` | `--force`, `--dry-run` | Cascade-archive group and all descendant groups/tasks. Prompts y/N unless `--force`. |
| `group mv` | `title` | `--parent TITLE` **or** `--to-top` (required), `--dry-run` | Reparent under another group, or `--to-top` to promote to root level; `--dry-run` previews the diff |
| `group assign` | `task title` | — | Assign task to group |
| `group unassign` | `task` | — | Unassign task from its group |
Edges between groups (and any other node types) live under the top-level `stx edge` command — see the `stx edge` section. Use the typed ref form `group:<title>` with `--source-parent`/`--target-parent` when group titles collide under different parents.

```sh
stx group create "Backend" --desc "Core API services"
stx group create "Auth" --parent "Backend"
stx group assign task-0005 "Auth"
stx group ls
stx group mv "Auth" --parent "Frontend"
stx group mv "Backend" --to-top  # promote to root level
stx edge create --source "group:Sprint 2" --target "group:Sprint 1" --kind blocks
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
stx config del active_workspace
```

**Active workspace storage:** `active_workspace` is stored in `tui.toml`. A legacy `~/.local/share/stx/active-workspace` file is still read as a fallback for one release; writes no longer go there.

---

## `stx tui [--db PATH]`

Launches the Textual TUI interface. No JSON output. Useful for interactive exploration — not scripted workflows.

**Keybindings** (selected): `w` focus tree, `b` focus board, `e` edit selected entity, `m` edit metadata on selected entity (task/workspace/group), `n` new resource, `s` switch workspace, `[`/`]` move task across statuses, `r` refresh, `ctrl+q` quit. The metadata editor is reached by pressing `m` on a focused kanban task card or any entity node in the workspace tree; it presents editable key/value rows with add/delete buttons and atomically bulk-replaces the entity's metadata blob on save via `service.replace_*_metadata`. Keys are normalized to lowercase before comparison so retyping a key's case is a no-op.

Switching workspace via the left-panel tree is an in-session focus change only; it does not modify the active workspace persisted on disk. Use `stx workspace use` or `stx config set active_workspace` to change the terminal default.

---

## Task identifier resolution

Every task-referencing command auto-detects whether the argument is an ID or a title. Numeric forms (`1`, `task-0001`, `#1`, `0001`) are tried first; anything else is looked up as a title on the active workspace. A task whose title literally looks like `task-NNNN` would be resolved as an ID, not a title — avoid such titles.

---

## JSON `data` Shapes by Command

| Command | `data` shape |
|---|---|
| `task create` | full TaskDetail (with `status`, `group`, `edge_sources`, `edge_targets`, `history`, `metadata`). `edge_sources`/`edge_targets` each is a list of `{task: Task, kind: str}`. |
| `task edit`, `task archive`, `task mv` | full TaskDetail (same shape as `task show`) |
| `task edit --dry-run`, `group edit/rename/mv --dry-run` | `EntityUpdatePreview`: `{entity_type, entity_id, label, before, after}` |
| `task mv --dry-run` | `TaskMovePreview`: `{task_id, title, from_status, to_status, from_position, to_position}` |
| `workspace create/rename` | full Workspace object |
| `workspace archive` | `{"workspace": {...Workspace}, "active_cleared": bool}` — `active_cleared` is `true` when the archived workspace was the active workspace and the active-workspace pointer was cleared as a side-effect. **Note:** this is the only archive command that returns an envelope rather than a bare entity — the `active_cleared` field represents a CLI state side-effect that cannot be inferred from the workspace object alone. |
| `status create/rename/archive` | full Status object |
| `status order` | `{"workspace_id": N, "statuses": [{"id": N, "name": str}, ...]}` |
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
| `task transfer --dry-run` | `{"task_id": N, "task_title": str, "source_workspace_id": N, "target_workspace_id": N, "target_status_id": N, "can_move": bool, "blocking_reason": str\|null, "edge_ids": [...], "is_archived": bool}` |
| `task ls` | `[{"status": {...Status}, "tasks": [{...TaskListItem}]}, ...]` — grouped by status, mirrors text output. Each element has a full Status object and a `tasks` array of TaskListItem objects. |
| `workspace ls` | array of Workspace objects with `"active": bool` field |
| `status ls` | array of Status objects |
| `group ls` | array of GroupRef objects |
| `task show` | full TaskDetail (with `status`, `group`, `edge_sources`, `edge_targets`, `history`, `metadata`) |
| `group show` | GroupDetail with `tasks`, `children` arrays, and `metadata` dict |
| `workspace ls` / `group ls` | entities include their `metadata` dicts |
| `task log` | array of TaskHistory objects |
| `workspace show` | `{"view": {"workspace": {...}, "statuses": [...]}, "groups": [...]}` |
| `export` | `{"markdown": "..."}` or `{"output_path": "...", "bytes": N}` when `-o FILE` |
| `backup` | `{"source": "...", "dest": "...", "bytes": N}` |
| `info` | `{"db": {"path": str, "exists": bool}, "wal": {...}, "shm": {...}, "active_workspace": {...}}` |
| `task meta ls`, `workspace meta ls`, `group meta ls` | `[{"key": "...", "value": "..."}]` (sorted; empty list if no metadata) |
| `task meta get/set/del`, `workspace meta get/set/del`, `group meta get/set/del` | `{"key": "...", "value": "..."}` |
| `config ls` | full TuiConfig dict: `{theme, show_task_descriptions, show_archived, confirm_archive, default_priority, auto_refresh_seconds, active_workspace, status_order}` |
| `config get` | `{"key": str, "value": any}` |
| `config set`, `config del` | `{"key": str, "value": any}` — value after write |

> **`task ls` vs `workspace show`:** `task ls --json` returns `[{status, tasks}]` — tasks grouped by status, matching the text output. `workspace show` returns the richer kanban context view (`{"view": {"workspace": {...}, "statuses": [...]}, "groups": [...]}`) for full workspace snapshot.
