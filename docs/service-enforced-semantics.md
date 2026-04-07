# Service Layer Business Rules

Business rules enforced by the service layer (`service.py`). These complement the
database-enforced rules in `db-enforced-semantics.md`. Rules marked **defense-in-depth**
are also enforced by the schema; the service layer re-validates them to produce
clear error messages instead of opaque `IntegrityError` exceptions.

---

## Cycle Detection (service-only)

- **Task dependency cycles are forbidden.** Before adding a dependency A → B, the
  service walks the transitive closure from B. If A is reachable, the dependency
  would create a cycle and is rejected. The database only prevents self-loops
  (`CHECK (task_id != depends_on_id)`); multi-hop cycles like A → B → C → A
  require application-level detection.
- **Group hierarchy cycles are forbidden.** Before reparenting a group, the service
  walks the subtree rooted at the group. If the proposed parent is a descendant,
  the reparent is rejected.

## Task Field Validation (defense-in-depth)

These constraints are also enforced by `CHECK` constraints in the schema, but the
service pre-validates them to provide clear messages.

- **Priority must be between 1 and 5.**
- **Position must be non-negative.**
- **If both start and finish dates are set, finish must be on or after start.**

## Cross-Entity Ownership (defense-in-depth)

These constraints are also enforced by composite foreign keys in the schema.

- **A task's status must belong to the same workspace as the task.**
- **A task's project must belong to the same workspace as the task.**
- **A dependency can only link tasks on the same workspace.**
- **A tag can only be applied to a task on the same workspace.**
- **A group's parent must belong to the same project.** (Also enforced by composite FK.)
- **A task's group must belong to the same project as the task.**

## Self-Reference (defense-in-depth)

- **A task cannot depend on itself.** Also enforced by `CHECK (task_id != depends_on_id)`.

## Duplicate Prevention (defense-in-depth)

Also enforced by partial unique indexes and primary keys in the schema; the
service layer translates `IntegrityError` into human-readable messages.

- **Duplicate dependencies are pre-checked** in the service layer before the insert.
- **Duplicate tag assignments** rely on the DB `PRIMARY KEY` constraint — no service pre-check; the `IntegrityError` is translated to a clear message.
- **Duplicate active names** for workspaces, statuses, projects, tasks, tags, and groups
  are rejected with entity-specific messages (via error translation).

## Archival Safety (service-only)

The database does not distinguish between active and archived rows for foreign key
or mutation purposes. These rules exist only in the service layer.

### Referencing archived entities is forbidden

Active entities cannot point to archived parents:

- **A task cannot be moved to an archived column.**
- **A task cannot be assigned to an archived project.**
- **A task cannot be assigned to an archived group.**

### Archiving parents with active children is forbidden

- **A status cannot be archived while it has active tasks.** Move or archive the
  tasks first.
- **A project cannot be archived while it has active tasks or groups.** Archive
  children first.
- **A workspace cannot be archived while it has active statuses, projects, or tasks.**

### Mutations on archived entities are allowed

Editing, tagging, adding dependencies to, or otherwise mutating an archived entity
is permitted. This supports fixing metadata before unarchiving.

## Cross-Workspace Move Preconditions (service-only)

- **An archived task cannot be moved to another workspace.**
- **A task with dependencies cannot be moved to another workspace.** Remove all
  dependencies (both directions) first.
- **The target status and project must belong to the target workspace.**
- **The target status and project must not be archived.**

### Cross-workspace move side effects

A cross-workspace move creates a new task on the target workspace and archives the
original. The following are NOT carried over:

- **Tags** — migrated by name: active tags from the original task are re-applied
  to the new task using the target workspace's tags (created on the target workspace if
  they don't exist yet).
- **group_id** — not carried over; groups are project-scoped and the task may
  have a new or no project on the target board.
- **History** — the original task retains its history; the new task starts fresh.

## Automatic Behaviors (service-only)

- **`tag_task` auto-creates the tag** on the workspace if it doesn't already exist,
  then applies it to the task. Calling `tag_task` is the only way to tag a task;
  it never fails with "tag not found."
- **Assigning a task to a group auto-sets the task's project** if the task has no
  project. If the task already has a different project, the assignment is rejected.
- **Archiving a group cascades:** active tasks are unassigned from the group,
  child groups are reparented to the archived group's parent (or promoted to
  top-level), and history is recorded for each unassigned task.

## Audit Trail (service-only logic, DB-enforced schema)

- **Task field changes are recorded as history entries** when a value actually
  changes (no-op updates are skipped). The set of trackable fields is fixed by
  the `TaskField` enum: title, description, status, project, priority, due date,
  position, archived, start date, finish date, group.
- **Each history entry records old value, new value, and source** (e.g., "cli",
  "tui").

## Error Translation

The service layer catches `sqlite3.IntegrityError` from the repository and
translates it into `ValueError` or `LookupError` with human-readable messages.
The CLI and TUI catch `ValueError` at the boundary and display the message
directly. Raw `IntegrityError` is still caught as a fallback safety net.

Translated error categories:

| SQLite error | Translated message |
|---|---|
| `UNIQUE constraint failed: workspaces.name` | "a workspace with this name already exists" |
| `UNIQUE constraint failed: projects.*` | "a project with this name already exists on this workspace" |
| `UNIQUE constraint failed: statuses.*` | "a status with this name already exists on this workspace" |
| `UNIQUE constraint failed: tags.*` | "a tag with this name already exists on this workspace" |
| `UNIQUE constraint failed: groups.*` | "a group with this title already exists in this project" |
| `UNIQUE constraint failed: tasks.*` | "a task with this title already exists on this workspace" |
| `UNIQUE constraint failed: task_dependencies.*` | "this dependency already exists" |
| `UNIQUE constraint failed: task_tags.*` | "task already has this tag" |
| `FOREIGN KEY constraint failed` | context-specific or generic FK message |
