# stx JSON Schema Reference

Documents the `--json` output shapes for every `stx` command. Shapes reflect current behavior and may evolve between releases — do not treat them as a frozen API contract.

---

## Envelope

All JSON output follows a two-field top-level envelope:

**Success** → stdout:
```json
{"ok": true, "data": <shape>}
```

**Error** → stderr:
```json
{"ok": false, "error": "<message>", "code": "<code>"}
```

Error codes and exit codes:

| code | exit | meaning |
|---|---|---|
| `validation` | 4 | Bad input, constraint violation, or non-interactive stdin without `--force` |
| `not_found` | 3 | Entity doesn't exist |
| `missing_active_workspace` | 5 | No active workspace set and `-w` not provided |
| `db_error` | 2 | SQLite error |

---

## Auto-detection

By default the CLI emits **text** when stdout is a terminal and **JSON** when stdout is a pipe or redirected. Override with global flags:

- `--json` — force JSON regardless of TTY
- `--text` — force text even when piped

---

## Common Field Types

These recur across shapes:

| field | type | notes |
|---|---|---|
| `id` | int | autoincrement DB id |
| `created_at` | int | Unix epoch seconds |
| `archived` | bool | soft-delete flag |
| `metadata` | object | `{key: value}` — lowercase-normalized string keys |
| `priority` | int | 1 (highest) – 5 (lowest) |
| `due_date` | int \| null | Unix epoch seconds |

---

## Task Commands

### `task create` / `task edit` / `task mv` / `task archive`

All mutation commands return a full **TaskDetail** object:

```json
{
  "ok": true,
  "data": {
    "id": 1,
    "title": "Fix login bug",
    "archived": false,
    "priority": 3,
    "due_date": null,
    "created_at": 1712700000,
    "description": null,
    "metadata": {},
    "status": {"id": 2, "name": "In Progress", "archived": false, "workspace_id": 1},
    "group": null,
    "tags": [],
    "edge_sources": [],
    "edge_targets": [],
    "history": []
  }
}
```

`group` is `null` when not assigned.  
`tags`, `edge_sources`, `edge_targets`, `history` are arrays (empty when none). Each element of `edge_sources` / `edge_targets` is a **TaskEdgeRef**: `{"task": Task, "kind": str}`.

**Naming convention — read literally:**

- `edge_sources` lists the **source tasks of edges touching this one** — i.e. incoming edges. Each `ref.task` is a task that points *at* the current one.
- `edge_targets` lists the **target tasks of edges from this one** — i.e. outgoing edges. Each `ref.task` is a task the current one points *at*.

Example: after `stx edge create --source task-0002 --target task-0001 --kind blocks`, `stx task show task-0002` shows the edge under `edge_targets` (task-2 points at task-1) with `ref.task = task-0001`, while `stx task show task-0001` shows the same edge under `edge_sources` (task-2 points at task-1) with `ref.task = task-0002`. `GroupDetail.edge_sources` / `edge_targets` follow the same convention on group edges.

### `task ls`

Returns a flat array of **TaskListItem** objects (status grouping is text-only):

```json
{
  "ok": true,
  "data": [
    {
      "id": 1,
      "title": "Fix login bug",
      "archived": false,
      "priority": 3,
      "due_date": null,
      "created_at": 1712700000,
      "status_id": 2,
      "tag_names": ["bug", "auth"]
    }
  ]
}
```

### `task show` / `task log`

`task show` returns the same **TaskDetail** shape as mutations.  
`task log` returns an array of **TaskHistory** entries:

```json
{
  "ok": true,
  "data": [
    {
      "id": 1,
      "task_id": 1,
      "field": "status_id",
      "old_value": "1",
      "new_value": "2",
      "changed_at": 1712700100,
      "source": "cli"
    }
  ]
}
```

### `task transfer` (live)

Returns `{"task": TaskDetail, "source_task_id": N}`. `task` is the new TaskDetail on the target workspace; `source_task_id` is the archived source task's id:

```json
{
  "ok": true,
  "data": {
    "task": {
      "id": 7,
      "title": "Fix login bug",
      "archived": false,
      "priority": 3,
      "due_date": null,
      "created_at": 1712700000,
      "description": null,
      "metadata": {},
      "status": {"id": 5, "name": "Backlog", "archived": false, "workspace_id": 2},
      "group": null,
      "tags": [],
      "edge_sources": [],
      "edge_targets": [],
      "history": []
    },
    "source_task_id": 1
  }
}
```

### `task transfer --dry-run`

Returns a **MoveToWorkspacePreview** object:

```json
{
  "ok": true,
  "data": {
    "task_id": 1,
    "task_title": "Fix login bug",
    "source_workspace_id": 1,
    "target_workspace_id": 2,
    "target_status_id": 5,
    "can_move": true,
    "edge_ids": [],
    "blocking_reason": null,
    "is_archived": false
  }
}
```

### Task Metadata (`task meta ls|get|set|del`)

`meta ls` — object of all key/value pairs:
```json
{"ok": true, "data": {"sprint": "2", "owner": "alice"}}
```

`meta get` — single value string:
```json
{"ok": true, "data": "alice"}
```

`meta set` / `meta del` — full updated metadata object:
```json
{"ok": true, "data": {"sprint": "2"}}
```

---

## Workspace Commands

### `workspace create` / `workspace edit`

```json
{
  "ok": true,
  "data": {"id": 1, "name": "dev", "archived": false, "metadata": {}}
}
```

### `workspace ls`

Array with injected `active` boolean:

```json
{
  "ok": true,
  "data": [
    {"id": 1, "name": "dev", "archived": false, "metadata": {}, "active": true}
  ]
}
```

### `workspace show`

Full **WorkspaceContext** — grouped kanban view:

```json
{
  "ok": true,
  "data": {
    "view": {
      "workspace": {"id": 1, "name": "dev", "archived": false, "metadata": {}},
      "statuses": [
        {
          "status": {"id": 1, "name": "To Do", "archived": false, "workspace_id": 1},
          "tasks": [<TaskListItem>, ...]
        }
      ]
    },
    "tags": [...],
    "groups": [...]
  }
}
```

### `workspace archive`

Unique shape — includes `active_cleared` side-effect flag:

```json
{
  "ok": true,
  "data": {
    "workspace": {"id": 1, "name": "dev", "archived": true, "metadata": {}},
    "active_cleared": true
  }
}
```

### `workspace use`

```json
{"ok": true, "data": {"id": 2, "name": "ops", "archived": false, "metadata": {}}}
```

### Workspace Metadata

Same four-verb pattern as task metadata; operates on active workspace (or `-w`).

---

## Status Commands

### `status create` / `status rename` / `status archive`

```json
{"ok": true, "data": {"id": 3, "name": "Review", "archived": false, "workspace_id": 1}}
```

### `status ls`

Array of Status objects.

### `status order`

```json
{
  "ok": true,
  "data": {
    "workspace_id": 1,
    "workspace": "dev",
    "statuses": [
      {"id": 1, "name": "To Do"},
      {"id": 2, "name": "In Progress"},
      {"id": 3, "name": "Done"}
    ]
  }
}
```

---

## Group Commands

### `group create` / `group edit` / `group mv` / `group archive`

```json
{
  "ok": true,
  "data": {
    "id": 1, "title": "Sprint 1", "description": null,
    "parent_id": null,
    "archived": false, "metadata": {}
  }
}
```

### `group ls`

Array of GroupRef objects:

```json
{
  "ok": true,
  "data": [
    {
      "id": 1, "title": "Sprint 1", "description": null,
      "parent_id": null,
      "archived": false, "metadata": {},
      "task_ids": [1, 2]
    }
  ]
}
```

### `group show`

**GroupDetail** — includes children and task list.

### `group assign` / `group unassign`

Returns full **TaskDetail** (same as `task show`).

### Group Edges (`group edge create|archive|ls|meta *`)

```json
{
  "ok": true,
  "data": {
    "source_id": 2,
    "source_title": "Sprint 2",
    "target_id": 1,
    "target_title": "Sprint 1",
    "workspace_id": 1,
    "kind": "blocks"
  }
}
```

`group edge ls` returns an array of the same shape (one **GroupEdgeListItem**
per active edge). `group edge meta ls|get|set|del` follow the four-verb pattern
documented under *Task Metadata* — same `{key, value}` shapes, with the edge
identified via `--source`/`--target` (and optional `--source-parent` /
`--target-parent` for disambiguation).

### Group Metadata

Same four-verb pattern as task metadata.

---

## Tag Commands

### `tag create` / `tag rename` / `tag archive`

```json
{"ok": true, "data": {"id": 1, "name": "bug", "archived": false, "workspace_id": 1}}
```

### `tag ls`

Array of Tag objects.

---

## Edge Commands (`edge create|archive|ls|meta *`)

### `edge create` / `edge archive`

```json
{
  "ok": true,
  "data": {
    "source_id": 2,
    "source_title": "Task B",
    "target_id": 1,
    "target_title": "Task A",
    "workspace_id": 1,
    "kind": "blocks"
  }
}
```

### `edge ls`

Array of **TaskEdgeListItem**:

```json
{
  "ok": true,
  "data": [
    {
      "source_id": 2,
      "source_title": "Task B",
      "target_id": 1,
      "target_title": "Task A",
      "workspace_id": 1,
      "kind": "blocks"
    }
  ]
}
```

### `edge meta ls|get|set|del`

Same four-verb shapes as `task meta` (see above). The target edge is identified
via `--source` + `--target`; no positional task.

---

## Standalone Commands

### `export`

```json
null
```
(`export` writes Markdown/JSON to stdout directly; `--json` envelope is a no-op.)

### `backup`

```json
{"ok": true, "data": {"path": "/path/to/backup.db"}}
```

### `info`

```json
{
  "ok": true,
  "data": {
    "db_path": "~/.local/share/stx/stx.db",
    "active_workspace_path": "~/.local/share/stx/active-workspace",
    "schema_version": 12
  }
}
```
