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
- Exit codes: `0` success · `1` lookup/validation/no active workspace · `2` db error · `130` interrupt

**Error codes:**

| code | meaning |
|---|---|
| `not_found` | entity doesn't exist |
| `validation` | bad argument value (including duplicate names and integrity violations) |
| `missing_active_workspace` | no active workspace set |
| `db_error` | SQLite error (exits 2) |

---

## Task Commands

### `todo task create <title> -S <status> [flags]`

`-S/--status` is **required** — there is no default status.

| Flag | Short | Default | Description |
|---|---|---|---|
| `--status` | `-S` | **required** | Target status name |
| `--desc` | `-d` | — | Description |
| `--project` | `-p` | — | Project name |
| `--priority` | `-P` | `1` | Priority 1–5 (convention: 1=lowest; range only is enforced) |
| `--due` | — | — | Due date `YYYY-MM-DD` |
| `--tag` | `-t` | — | Tag name (repeatable) |

```sh
todo task create "Write README" -S "To Do"
todo task create "Deploy to prod" -S Backlog --project "Q2 launch" -P 3 --due 2026-05-01
todo task create "Add tests" -S "To Do" --tag backend --tag ci
```

> **JSON and tags:** The `task create` JSON response returns the raw `Task` object which has no `tags` field. Tags attached via `--tag` are not reflected in the response. To see attached tags, follow up with `todo task show <task_num>` which returns a `TaskDetail` with a `tags` array.

---

### `todo task ls [flags]`

| Flag | Short | Default | Description |
|---|---|---|---|
| `--all` | `-a` | off | Include archived tasks |
| `--archived` | — | off | Show ONLY archived tasks |
| `--status` | `-S` | — | Filter by status name |
| `--project` | `-p` | — | Filter by project name |
| `--priority` | `-P` | — | Filter by priority (1–5) |
| `--search` | `-s` | — | Title substring search |
| `--group` | `-g` | — | Filter by group title |
| `--tag` | `-t` | — | Filter by tag name |

```sh
todo task ls
todo task ls --project "Q2 launch" --status "In Progress"
todo task ls --search auth --priority 3
todo task ls --tag backend --all
```

---

### `todo task show <task_num> [--by-title]`

Shows full task detail: description, history, dependencies, group, tags.

```sh
todo task show task-0001
todo task show "Write README" --by-title
```

---

### `todo task edit <task_num> [flags]`

All flags are optional; only provided fields are updated.

| Flag | Short | Default | Description |
|---|---|---|---|
| `--title` | — | — | New title |
| `--desc` | `-d` | — | New description |
| `--priority` | `-P` | — | New priority (1–5) |
| `--due` | — | — | New due date `YYYY-MM-DD` |
| `--project` | `-p` | — | Change project |
| `--tag` | `-t` | — | Add tag (repeatable) |
| `--untag` | — | — | Remove tag (repeatable) |
| `--by-title` | — | off | Resolve `task_num` as title string |

```sh
todo task edit task-0003 --priority 4 --due 2026-06-01
todo task edit task-0003 --tag urgent --untag backend
```

---

### `todo task mv <task_num> <status> [position] [flags]`

**Within-workspace only.** Use `todo task transfer` for cross-workspace moves.

| Arg/Flag | Description |
|---|---|
| `status` (positional) | Target status name |
| `position` (optional positional) | Integer position within status (default: `0` = top) |
| `--project` / `-p` | Also change the task's project |
| `--by-title` | Resolve task by title |

```sh
todo task mv task-0001 "In Progress"
todo task mv task-0001 Done 2          # position 2 within Done status
todo task mv task-0001 Backlog --project "Next sprint"
```

**Note:** `todo task done` does not exist. To mark done: `todo task mv <task> Done` (requires a status literally named "Done").

---

### `todo task rm <task_num> [--by-title]`

Soft-archives the task (`archived=true`). Not a hard delete. Tasks remain queryable with `--all` or `--archived`.

---

### `todo task log <task_num> [--by-title]`

Shows the full audit trail of field changes (TaskHistory).

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
3. **Fails** if the task has any dependencies (incoming or outgoing) — remove them first with `todo dep rm`

| Flag | Short | Required | Description |
|---|---|---|---|
| `--workspace` | — | **yes** | Target workspace name |
| `--status` | `-S` | **yes** | Status on target workspace |
| `--project` | `-p` | no | Project on target workspace |
| `--dry-run` | — | no | Preview without executing; validates blocking deps |
| `--by-title` | — | no | Resolve source task by title |

```sh
todo task transfer task-0001 --workspace ops --status Backlog
todo task transfer task-0001 --workspace ops --status Backlog --project infra
todo task transfer task-0001 --workspace ops --status Backlog --dry-run
```

> **Workspace flag disambiguation:** The global `-w/--workspace` selects the **source** workspace (or falls back to the active workspace). The transfer subcommand's own `--workspace` selects the **target** workspace. Both may appear on the same command line.


---

## `todo workspace` Subcommands

| Command | Args | Flags | Description |
|---|---|---|---|
| `workspace create` | `name` | `--statuses "A,B,C"` | Create workspace; auto-switches active; optionally seed statuses. `--statuses` takes a single comma-separated string (e.g. `--statuses "To Do,In Progress,Done"`). Quote the whole value. |
| `workspace ls` | — | `--all` / `-a` | List all workspaces; marks active workspace |
| `workspace use` | `name` | — | Switch active workspace |
| `workspace rename` | `[old] new` | — | 1 arg = rename active workspace; 2 args = rename named workspace |
| `workspace rm` | `[name]` | — | Archive workspace (default: active); clears active pointer if removing active |

```sh
todo workspace create work --statuses "To Do,In Progress,Done"
todo workspace use personal
todo workspace ls
todo workspace rename "work" "work-q2"
```

---

## `todo status` Subcommands

| Command | Args | Flags | Description |
|---|---|---|---|
| `status create` | `name` | — | Create a status on the active workspace |
| `status ls` | — | — | List statuses on active workspace |
| `status rename` | `old new` | — | Rename a status |
| `status rm` | `name` | `--reassign-to STATUS`, `--force` | Archive status; either reassign its tasks to another status, or `--force` to archive all tasks |

```sh
todo status create "Blocked"
todo status rm "Old Status" --reassign-to "Backlog"
todo status rm "Old Status" --force
```

---

## `todo project` Subcommands

| Command | Args | Flags | Description |
|---|---|---|---|
| `project create` | `name` | `--desc` / `-d` | Create project |
| `project ls` | — | — | List projects |
| `project show` | `name` | — | Show project detail |
| `project rm` | `name` | — | Archive project |

> **No `project rename`.** To rename: create a new project, reassign tasks via `todo task edit --project "new name"`, then archive the old one.

---

## `todo dep` Subcommands

Semantics: `todo dep create <task> <depends-on>` means **task is blocked by depends-on**. No `dep ls` — use `todo task show <task>` to see `blocked_by` and `blocks` arrays.

| Command | Args | Flags | Description |
|---|---|---|---|
| `dep create` | `task_num depends_on_num` | `--by-title` | Add dependency |
| `dep rm` | `task_num depends_on_num` | `--by-title` | Remove dependency |

```sh
todo dep create task-0003 task-0001   # task-0003 is blocked by task-0001
todo dep rm task-0003 task-0001
```

---

## `todo group-dep` Subcommands

Semantics: `todo group-dep create <group> <depends-on>` means **group is blocked by depends-on**. Groups are resolved by title within the active workspace's projects.

| Command | Args | Flags | Description |
|---|---|---|---|
| `group-dep create` | `group_title depends_on_title` | — | Add group dependency |
| `group-dep rm` | `group_title depends_on_title` | — | Remove group dependency |

```sh
todo group-dep create "Sprint 2" "Sprint 1"
todo group-dep rm "Sprint 2" "Sprint 1"
```

---

## `todo tag` Subcommands

Tags are workspace-scoped. Many-to-many with tasks. `todo task create`/`todo task edit` auto-create tags that don't exist yet.

| Command | Args | Flags | Description |
|---|---|---|---|
| `tag create` | `name` | — | Create a tag (workspace-scoped) |
| `tag ls` | — | `--all` / `-a` | List tags (include archived with `-a`) |
| `tag rm` | `name` | `--unassign` | Archive tag; `--unassign` strips it from all tasks first |

> **No `tag rename`.** To rename: create new tag, reassign via `todo task edit --tag new --untag old`, archive old.

```sh
todo tag create backend
todo tag ls
todo tag rm backend --unassign
```

---

## `todo group` Subcommands

Groups are project-scoped hierarchical collections of tasks. All group commands accept `--project/-p` to scope to a project.

| Command | Args | Flags | Description |
|---|---|---|---|
| `group create` | `title` | `--project/-p` (**required**), `--parent TITLE` | Create group; optionally nested under parent |
| `group ls` | — | `--project/-p`, `--all/-a`, `--tree` | List (flat or tree view) |
| `group show` | `title` | `--project/-p` | Show detail with ancestry |
| `group rename` | `title new_title` | `--project/-p` | Rename |
| `group rm` | `title` | `--project/-p` | Archive |
| `group mv` | `title` | `--parent` (**required**), `--project/-p` | Reparent; `--parent ''` promotes to top-level |
| `group assign` | `task group_title` | `--project/-p`, `--by-title` | Assign task to group |
| `group unassign` | `task` | `--by-title` | Unassign task from its group |

```sh
todo group create "Backend" --project "API rewrite"
todo group create "Auth" --project "API rewrite" --parent "Backend"
todo group assign task-0005 "Auth" --project "API rewrite"
todo group ls --project "API rewrite" --tree
todo group mv "Auth" --parent "Frontend" --project "API rewrite"
todo group mv "Backend" --parent '' --project "API rewrite"  # promote to top-level
```

---

## `todo export`

Exports the **entire database**. Default format is JSON; pass `--md` for Markdown with Mermaid dependency graphs.

| Flag | Short | Description |
|---|---|---|
| `--md` | — | Export as Markdown instead of JSON |
| `--output` | `-o` | Write to file instead of stdout (creates parent dirs) |

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

JSON `data` shape: `{"db": "...", "wal": "...", "shm": "...", "active_workspace": "...", "existing": [...], "reset_command": "python scripts/wipe_db.py"}`

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

---

## `--by-title` Flag

Resolves a task by title string instead of `task-NNNN` ID. Accepted by:

`task show` · `task edit` · `task mv` · `task transfer` · `task rm` · `task log` · `dep create` · `dep rm` · `group assign` · `group unassign`

---

## JSON `data` Shapes by Command

| Command | `data` shape |
|---|---|
| `task create`, `task edit`, `task rm`, `task mv` | full Task object |
| `workspace create/rename/rm` | full Workspace object |
| `status create/rename/rm` | full Status object |
| `project create/rm` | full Project object |
| `tag create/rm` | full Tag object |
| `dep create/rm` | `{"task_id": N, "depends_on_id": N}` |
| `group-dep create/rm` | `{"group_id": N, "depends_on_id": N}` |
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
| `task show` | full TaskDetail (with `status`, `project`, `group`, `tags`, `blocked_by`, `blocks`, `history`) |
| `project show` | ProjectDetail with `tasks` array |
| `group show` | GroupDetail with `tasks` and `children` arrays |
| `task log` | array of TaskHistory objects |
| `context` | `{"view": {"workspace": {...}, "statuses": [...]}, "projects": [...], "tags": [...], "groups": [...]}` |
| `export` | `{"markdown": "..."}` or `{"output_path": "...", "bytes": N}` when `-o FILE` |
| `backup` | `{"source": "...", "dest": "...", "bytes": N}` |
| `info` | `{"db": "...", "wal": "...", "shm": "...", "active_workspace": "...", "existing": [...], "reset_command": "..."}` |

> **`context` vs `ls` shape asymmetry:** `ls` returns `{"workspace": {...}, "statuses": [...]}` directly at the top level. `context` wraps the same workspace+statuses shape inside a `"view"` key — they are **not** interchangeable payloads.
