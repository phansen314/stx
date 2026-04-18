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
| `6` | `conflict` — optimistic lock exhausted after max CAS retries |
| `130` | interrupted (SIGINT) |

---

## Archive Semantics

Archives are **soft-deletes** — rows are never removed from the database; the `archived` flag is set to `1`.

- **Visibility:** archived entities are hidden by default. Use `--archived include` or `--archived only` on `ls` commands where supported (`workspace ls`, `status ls`, `group ls`, `task ls`).
- **No unarchive command.** There is no `unarchive` or `restore` subcommand. To restore an entity, use the SQLite CLI directly: `sqlite3 ~/.local/share/stx/stx.db "UPDATE tasks SET archived=0 WHERE id=N"`.
- **Cascade archive:** `workspace archive` and `group archive` cascade to all descendants (statuses, tasks, groups where applicable). See individual archive subcommand rows for cascade scope.

---

## Path-based Refs

Group and task arguments accept these ref shapes:

| Form | Meaning |
|---|---|
| `foo` | Bare title — workspace-wide lookup. Ambiguity (multi-match) errors with a hint to use a path ref. In polymorphic edge contexts, bare resolves as a task. |
| `/A` | **Root group `A`** — leading-slash anchor (Unix-style absolute path) makes single-segment refs unambiguously group paths. Useful in polymorphic edge contexts to reference a root group without the `group:` prefix. |
| `A/B/C` (or `/A/B/C`) | **Group path** — strict walk from root: `A` → `B` → `C`. Each segment must exist as a non-archived child of the previous. Leading slash is cosmetic for multi-segment paths. |
| `A/B:leaf` (or `/A/B:leaf`) | **Task path** — group prefix `A/B`, then task title `leaf` scoped to that group. |
| `:rootleaf` | **Root task** — no group prefix, task `rootleaf` with `group_id IS NULL`. |

**Where paths apply:**
- Group ref args/flags: `group show <ref>`, `group edit <ref>`, `group log <ref>`, `group archive <ref>`, `group mv <ref>`, `group assign <task> <ref>`, `group meta * <ref>`, `group create <ref>` (path-as-title), `--parent <ref>`, `task create -g <ref>`, `task ls -g <ref>`, `task edit -g <ref>`.
- Task ref args/flags: `task show|edit|mv|transfer|archive|log|done|undone|meta * <ref>`, `group assign <ref> <group>`, `group unassign <ref>`.
- Edge `--source` / `--target` (polymorphic): type is **inferred** from delimiters when no explicit prefix is given:
  - `task-NNNN` / `#N` / plain int → task by id
  - `/A` or `/A/B/C` (leading slash) → group path (single-segment included)
  - `A/B/C` (only `/`, multi-segment) → group path
  - `A:foo`, `:foo`, `A/B:foo` (contains `:`) → task path
  - bare title (no delimiters) → task by title
  - Explicit prefixes `group:`, `task:`, `workspace:`, `status:` always override inference; the suffix uses the same path syntax. E.g. `--source group:A/B/C` or `--target task:A/B:leaf`.
  - Examples:
    - `--source /A/B/C --target D:task0` — group→task, no prefixes needed.
    - `--source /A --target /B` — root group A → root group B.
    - `--source task-0001 --target /A` — task → root group A.

**Title constraints:** group and task titles cannot contain `/` or `:` (reserved for path syntax). Service-layer validation rejects offending writes; a `CHECK` constraint enforces it on fresh databases. Pre-existing rows were auto-renamed by migration 022 (`/`/`:` → `__`, collisions get `__N` suffix).

**Validation errors:**
- Title with `/` or `:` → exit 4 (`validation`).
- Path walk missing a segment → exit 3 (`not_found`), names the failing segment + path so far ("group path segment 'c' not found under a/b").
- Bare-title ambiguity → exit 3, message hints to use a path ref.
- Task ref passed where a group ref is expected (or vice versa) → exit 4 ("expected group ref, got task path: 'A:foo'").

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
| `--group` | `-g` | — | Group title or path (e.g. `Frontend/Login`) |

```sh
stx task create "Write README" -S "To Do"
stx task create "Deploy to prod" -S Backlog --priority 3 --due 2026-05-01
stx task create "Fix layout" -S "To Do" --group "Frontend/Login"
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
| `--group` | `-g` | — | Filter by group title or path (flat — no subgroup recursion) |

```sh
stx task ls
stx task ls --group "Sprint 1" --status "In Progress"
stx task ls --group "Backend/Auth"             # path ref disambiguates collisions
stx task ls --search auth --priority 3
stx task ls --archived include
```

---

### `stx task show <task>`

Shows full task detail: description, history, edges (`edge_sources` / `edge_targets` each carrying a `kind`), group. `<task>` accepts numeric IDs (`1`, `task-0001`, `#1`), a bare title (workspace-wide), or a path ref (`A/B:leaf` for a task in group `A/B`; `:rootleaf` for a root task with no group).

```sh
stx task show task-0001
stx task show "Write README"
stx task show "Backend/Auth:apply-migrations"
stx task show ":rootleaf"
```

---

### `stx task edit <task_num> [flags]`

All flags are optional; only provided fields are updated.

| Flag | Short | Default | Description |
|---|---|---|---|
| `--title` | — | — | New title |
| `--desc` | `-d` | — | New description |
| `--priority` | `-p` | — | New priority integer |
| `--due` | — | — | New due date `YYYY-MM-DD` |
| `--group` | `-g` | — | Group title or path to assign (e.g. `Backend/Auth`); pass `""` to unassign |
| `--dry-run` | — | off | Preview the field diff without writing (ignores `--group`) |

```sh
stx task edit task-0003 --priority 4 --due 2026-06-01
stx task edit task-0003 --priority 5 --dry-run
stx task edit task-0003 --group "backend"      # assign
stx task edit task-0003 --group ""             # unassign
```

`--group` and `stx group assign` / `stx group unassign` funnel through the same
service path (`update_task` / `_update_task_body`) — either surface is
equivalent.

---

### `stx task mv <task> --status <status> [--dry-run]`

**Within-workspace only.** Use `stx task transfer` for cross-workspace moves.

| Arg/Flag | Description |
|---|---|
| `--status` / `-S` | Target status name (**required**) |
| `--dry-run` | Preview from/to status without writing |

```sh
stx task mv task-0001 --status "In Progress"
stx task mv task-0001 -S Done
stx task mv task-0001 -S Done --dry-run
```

---

### `stx task done <task>`

Mark a task done independent of its status. True no-op (no write, no version bump) if already done. The `done` flag is sticky — it is not cleared by subsequent status moves. Use `stx task undone` to clear it.

```sh
stx task done task-0001
stx task done "Write README"
```

Returns full TaskDetail. Text output: `"marked task-NNNN done"` or `"task-NNNN already done"`.

---

### `stx task undone <task> [--force]`

Clear the done flag on a task. Gated to prevent accidental reverts:
- **Non-interactive stdin** (pipe, CI): `--force` is required; the command exits with a validation error otherwise.
- **Interactive terminal**: prompts `"proceed? [y/N]"` unless `--force` is passed.

True no-op if already not done.

| Flag | Description |
|---|---|
| `--force` | Skip confirmation prompt |

```sh
stx task undone task-0001 --force
```

Returns full TaskDetail. Text output: `"marked task-NNNN not done"` or `"task-NNNN already not done"`.

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
| `status edit` | `name` | `--name NEW`, `--terminal`, `--no-terminal` | Edit status. `--name` renames. `--terminal` / `--no-terminal` are mutually exclusive: mark/unmark the status as terminal. Tasks moved into (or created in) a terminal status auto-set `done=true`; leaving a terminal status does not clear `done`. |
| `status order` | `status1 status2 ...` | — | Set the TUI display order for statuses on the active workspace (or `-w`). Writes `~/.config/stx/tui.toml`. Partial ordering allowed — unlisted statuses fall to the end. |
| `status archive` | `name` | `--reassign-to STATUS`, `--force`, `--dry-run` | Archive status. `--dry-run` previews without executing. `--reassign-to` moves tasks to another status before archiving. `--force` cascade-archives all tasks in the status instead — when active tasks exist, a warning line is emitted to stderr before the archive runs (no prompt, pipe-friendly). Neither flag triggers a confirmation prompt. Without either flag the service layer blocks on active tasks and exits with an error. |

```sh
stx status create "Blocked"
stx status order backlog "in progress" review done
stx status archive "Old Status" --dry-run
stx status archive "Old Status" --reassign-to "Backlog"
stx status archive "Old Status" --force
```

---

## `stx edge` Subcommands

Edges are polymorphic directional links with a free-form `kind` label and their own metadata blob. Endpoints are typed refs: `task-NNNN` / `#NNNN` / `<task ref>` for tasks, `group:<title-or-path>` for groups, `task:<task-path>` for tasks, `workspace:<name>` for workspaces, `status:<name>` for statuses. Group and task suffixes accept full path syntax (`group:A/B/C`, `task:A/B:leaf`). Cross-type edges are allowed (task→group, group→workspace, status→status, etc.); status edges are pure annotation and carry no write-path semantics. Flags are explicit: `--source X --target Y --kind blocks` means **X points to Y with kind `blocks`**. Every edge subcommand accepts `-s` / `-t` / `-k` as short forms for `--source` / `--target` / `--kind`. The PK is `(from_type, from_id, to_type, to_id, kind)` — multiple kinds between the same node pair coexist; re-adding the same `(source, target, kind)` tuple clears the metadata blob and flips `archived = 0`. Self-loops are rejected by a DB CHECK. Cross-workspace edges are rejected at the service layer.

**Kind constraint:** lowercase `[a-z0-9_.-]+`, 1-64 characters. Enforced by the service layer's `_normalize_edge_kind` and a DB `CHECK (kind GLOB '[a-z0-9_.-]*' AND length(kind) BETWEEN 1 AND 64)`.

**Acyclic flag:** each edge carries `acyclic` (default: `1` for `kind in {blocks, spawns}`, `0` otherwise). Cycle detection runs over the union of active acyclic edges — so mixing `blocks` and `spawns` in a cycle is rejected, but `informs` / `references` / `related-to` can freely form cycles. Override with `--acyclic` / `--no-acyclic`.

**Group disambiguation:** when multiple groups share a title under different parents, use a path ref in the suffix — e.g. `group:Backend/Auth` resolves only the `Auth` group whose parent is `Backend`. The legacy `--source-parent` / `--target-parent` flags were removed in 0.15.

| Command | Args | Flags | Description |
|---|---|---|---|
| `edge create` | — | `--source REF --target REF --kind KIND` (all required), `--acyclic`/`--no-acyclic` | Add an edge from source to target with the given kind. |
| `edge show` | — | `--source REF --target REF --kind KIND` (all required) | Show full edge detail (endpoints, kind, acyclic, archived, metadata, filtered history). |
| `edge edit` | — | `--source REF --target REF --kind KIND` (all required), `--acyclic`/`--no-acyclic` | Mutate the `acyclic` flag. Kind and endpoints are immutable (part of PK). Flipping off→on re-runs cycle detection and rejects the edit if a cycle would result. |
| `edge log` | — | `--source REF --target REF --kind KIND` (all required) | Show journal history attributable to this (endpoint, kind) pair. **Caveat:** metadata events (`meta.*`) are journaled with `entity_id = from_id` only and cannot be disambiguated when multiple edges share a source — `edge log` captures endpoint/kind/acyclic/archived events but may omit metadata events for source nodes with multiple outgoing edges. |
| `edge archive` | — | `--source REF --target REF --kind KIND` (all required) | Soft-archive the active edge. Re-create via `edge create`. |
| `edge ls` | — | `--source REF`, `--target REF`, `--kind KIND` | List active edges on the active workspace; filters are optional. Both endpoints must be active (archived endpoints are hidden). |
| `edge meta ls` | — | `--source REF --target REF --kind KIND` | List all metadata on the edge. |
| `edge meta get` | `key` | `--source REF --target REF --kind KIND` | Read a single metadata value. |
| `edge meta set` | `key value` | `--source REF --target REF --kind KIND` | Write or overwrite a metadata value. Same charset/length rules as entity metadata (lowercase key, `[a-z0-9_.-]+`, 64-char key cap, 500-char value cap). |
| `edge meta del` | `key` | `--source REF --target REF --kind KIND` | Remove a metadata key. |

```sh
stx edge create --source task-0003 --target task-0001 --kind blocks
stx edge create --source task-0002 --target "group:Auth" --kind informs
stx edge create -s /A/B -t D:task0 -k blocks      # short forms work everywhere
stx edge show --source task-0003 --target task-0001 --kind blocks
stx edge edit --source task-0003 --target task-0001 --kind blocks --no-acyclic
stx edge log --source task-0003 --target task-0001 --kind blocks
stx edge ls
stx edge ls --kind blocks
stx edge ls --source task-0003
stx edge meta set --source task-0003 --target task-0001 --kind blocks rationale "depends on refactor"
stx edge meta ls --source task-0003 --target task-0001 --kind blocks
stx edge archive --source task-0003 --target task-0001 --kind blocks
```

---

## `stx group` Subcommands

Groups are workspace-scoped hierarchical collections of tasks. Root groups have no parent (`parent_id IS NULL`); nested groups specify `--parent` or use a path-as-title (`group create A/B/new`). All group commands resolve the group title within the active workspace (or `-w`); a bare title performs an ambiguous workspace-wide lookup, while a path ref (`A/B`) walks strictly from root.

**Title constraints:** group and task titles cannot contain `/` or `:` — both are reserved for path syntax. Pre-existing offenders are auto-renamed to `__` equivalents by migration 022.

| Command | Args | Flags | Description |
|---|---|---|---|
| `group create` | `title-or-path` | `--parent TITLE-OR-PATH`, `--desc/-d` | Create group. If `title` contains `/`, the leaf segment is the new title and the prefix is the parent path (mutually exclusive with `--parent`). |
| `group ls` | — | `--archived {hide,include,only}` (default `hide`) | List groups (flat, root-level by default) |
| `group show` | `title-or-path` | — | Show detail with ancestry. Path ref disambiguates collisions. |
| `group edit` | `title-or-path` | `--title NEW`, `--desc/-d`, `--dry-run` | Edit group fields; `--title` renames the group; `--dry-run` previews the diff |
| `group log` | `title-or-path` | — | Show journal / change history for the group. |
| `group archive` | `title-or-path` | `--force`, `--dry-run` | Cascade-archive group and all descendant groups/tasks. Prompts y/N unless `--force`. |
| `group mv` | `title-or-path` | `--parent TITLE-OR-PATH` (required), `--dry-run` | Reparent. Pass `--parent /` to promote to root level; otherwise resolve the new parent. `--dry-run` previews the diff. |
| `group assign` | `task title-or-path` | — | Assign task to group |
| `group unassign` | `task` | — | Unassign task from its group |
Edges between groups (and any other node types) live under the top-level `stx edge` command — see the `stx edge` section. Use the typed ref form `group:<title-or-path>` (e.g. `group:Backend/Auth`) when group titles collide under different parents.

```sh
stx group create "Backend" --desc "Core API services"
stx group create "Backend/Auth"             # path-as-title creates Auth under Backend
stx group create "OAuth" --parent "Backend/Auth"
stx group assign task-0005 "Backend/Auth"
stx group ls
stx group show "Backend/Auth"               # path ref disambiguates collisions
stx group mv "Backend/Auth" --parent "/Frontend"
stx group mv "Backend" --parent /           # promote to root level
stx edge create --source "group:Backend/Auth" --target "group:Frontend/Login" --kind blocks
stx edge create --source "task:Backend:apply-migrations" --target "task:Frontend:render-form" --kind blocks
```

---

## `stx next` — Next Actionable Tasks

Computes the ready frontier (and optionally the full topological order) by running Kahn's algorithm over the active acyclic edge DAG.

**How it works:**
- Loads all not-done, non-archived tasks for the active workspace.
- Loads all active acyclic edges of the specified kind(s) (default: `blocks`).
- Expands group endpoints to their member task IDs so a `group-A blocks group-B` edge means every not-done task in A must be done before any task in B becomes ready.
- **Ready**: tasks whose blockers (expanded to individual task IDs) are all done.
- **Blocked**: not-done tasks with the IDs of their pending blockers (always non-empty per entry).

| Flag | Default | Description |
|---|---|---|
| `--rank` | off | Sort the ready list by (priority desc, due\_date asc, id asc). In `--include-blocked` mode applies the same key as a tiebreaker within each wave. |
| `--include-blocked` | off | Return the full topological order of all not-done tasks (frontier first, then their dependents). `blocked` is empty in this mode. |
| `--limit N` | — | Cap the ready list to N items after ranking/sorting. Does not limit the blocked list. |
| `--edge-kind KIND` | `blocks` | Edge kind(s) to use when building the DAG. Repeatable: `--edge-kind blocks --edge-kind spawns`. Only acyclic edges of the given kinds are included. |

**Text output:**

```
Ready:
  task-0001  p9  Provision cloud account
  task-0003  p7  Set up load balancer

Blocked:
  task-0005  p8  Scaffold REST API  (blocked by: task-0001, task-0003)
```

**JSON output** (`NextTasksView`):
```json
{
  "ok": true,
  "data": {
    "workspace_id": 1,
    "ready": [<TaskListItem>, ...],
    "blocked": [
      {"task": <TaskListItem>, "blocked_by": [1, 3]},
      ...
    ]
  }
}
```

`blocked_by` is always a non-empty array of task IDs (tasks that are not yet done and gate this task).

```sh
stx next
stx next --rank
stx next --rank --limit 3
stx next --include-blocked
stx --json next --rank --edge-kind blocks --edge-kind spawns
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

## `stx graph`

Generates a DOT or Mermaid graph file from the active workspace's edges. Writes to a temp file by default; use `--output` for an explicit path. The file contains source text (not a rendered image) — open it with `xdot`, paste into mermaid.live, or render via `dot -Tpng`.

| Flag | Short | Default | Description |
|---|---|---|---|
| `--format` | `-f` | `dot` | Output format: `dot` (Graphviz) or `mermaid` |
| `--kind` | `-k` | all | Filter edges by kind. Repeatable: `-k blocks -k spawns` |
| `--output` | `-o` | temp file | Write to file instead of temp file |

```sh
stx graph                                    # all edges → temp .dot file
stx graph -f mermaid -o /tmp/deps.mmd        # mermaid format, explicit path
stx graph -k blocks -k spawns                # only blocks + spawns edges
stx graph -o graph.dot && xdot graph.dot     # render with xdot
```

JSON `data` shape:
- Edges found: `{"path": "/tmp/stx-graph-XXXX.dot", "format": "dot"}`
- No edges: `{"path": null}`

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

## `stx hook` Subcommands

Read-only inspection of the hooks engine's configuration and event surface. Hooks themselves live in `~/.config/stx/hooks.toml` (see `src/stx/hooks.py`); these commands don't mutate that file.

| Subcommand | Args | Description |
|---|---|---|
| `ls` | `[--workspace NAME \| --globals-only] [--event NAME] [--path FILE]` | List configured hooks with optional filters. |
| `events` | — | List every valid `HookEvent` value (declaration order, grouped by entity). |
| `validate` | `[--path FILE]` | Report schema errors in `hooks.toml`. Exits 0 when valid, exit 4 when invalid (the structured error list is still emitted — JSON consumers get the full `data.errors` payload before the nonzero exit). |
| `schema` | `[-o FILE] [--overwrite]` | Print the bundled `hook_events.schema.json` (JSON Schema draft 2020-12). `--output` writes to a file instead of stdout; `--overwrite` is required if the destination already exists. |

**Filtering notes on `ls`:** `--event` must be a valid event name (invalid → exit 4 with the valid list). `--workspace` on `ls` is an exact match against each hook's `workspace` field in the config file; it is **unrelated** to the global `-w/--workspace` flag and the active workspace. `--globals-only` restricts to hooks without a `workspace` field and is mutually exclusive with `--workspace`.

**Broken configs on `ls`:** if `hooks.toml` fails to parse or has invalid entries, `ls` exits 4 with a message pointing at `stx hook validate` for the full error list.

**Path override:** `--path` on `ls` and `validate` points at an alternate `hooks.toml` (default: `~/.config/stx/hooks.toml`). Missing file is treated as an empty config.

```
stx hook events
stx hook ls
stx hook ls --event task.created
stx hook ls --globals-only
stx hook ls --workspace myws --path /tmp/staged-hooks.toml
stx hook validate                            # exit 0 if valid, 4 otherwise
stx hook schema -o /tmp/hook-events.schema.json --overwrite
```

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
| `task done`, `task undone` | full TaskDetail |
| `next` | `NextTasksView`: `{workspace_id, ready: [TaskListItem], blocked: [{task: TaskListItem, blocked_by: [int]}]}` |
| `task edit --dry-run`, `group edit/rename/mv --dry-run` | `EntityUpdatePreview`: `{entity_type, entity_id, label, before, after}` |
| `task mv --dry-run` | `TaskMovePreview`: `{task_id, title, from_status, to_status}` |
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
