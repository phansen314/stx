# Service Layer Business Rules

Business rules enforced by the service layer (`service.py`). These complement the
database-enforced rules in `db-enforced-semantics.md`. Rules marked **defense-in-depth**
are also enforced by the schema; the service layer re-validates them to produce
clear error messages instead of opaque `IntegrityError` exceptions.

---

## Cycle Detection

**Edge cycles: not enforced.** Deferred pending blocking-kind semantics rework —
with `kind`-labelled edges, "cycle" is kind-dependent (an A→B "blocks" and a
B→A "related-to" are not logically a cycle). The DB still rejects self-loops
via `CHECK (source_id != target_id)` on both `task_edges` and `group_edges`.
Multi-hop cycles are currently allowed at all layers.

- **Group hierarchy cycles are forbidden.** Before reparenting a group, the service
  walks the subtree rooted at the group. If the proposed parent is a descendant,
  the reparent is rejected. (This is unchanged — the `parent_id` hierarchy on
  `groups` is separate from the edge system on `group_edges`.)

## Task Field Validation (defense-in-depth)

These constraints are also enforced by `CHECK` constraints in the schema, but the
service pre-validates them to provide clear messages.

- **Priority must be between 1 and 5.**
- **Position must be non-negative.**
- **If both start and finish dates are set, finish must be on or after start.**

## Cross-Entity Ownership (defense-in-depth)

These constraints are also enforced by composite foreign keys in the schema.

- **A task's status must belong to the same workspace as the task.**
- **A task edge can only link tasks on the same workspace.** Enforced by the composite FK `task_edges.(source_id, workspace_id) → tasks(id, workspace_id)`.
- **A group edge can only link groups on the same workspace.** Enforced by the composite FK `group_edges.(source_id, workspace_id) → groups(id, workspace_id)`.
- **A group's parent must belong to the same workspace.** (Also enforced by composite FK.)

## Self-Reference (defense-in-depth)

- **A task edge cannot link a task to itself.** Also enforced by `CHECK (source_id != target_id)` on `task_edges`. Symmetric rule for group edges.

## Duplicate Prevention (defense-in-depth)

Also enforced by partial unique indexes and primary keys in the schema; the
service layer translates `IntegrityError` into human-readable messages.

- **Duplicate edges are pre-checked** in the service layer: `add_task_edge`/`add_group_edge` reject insert when an active edge with the same `(source_id, target_id)` already exists (regardless of kind). The DB PK is the last line of defense.
- **Edge kind validation:** `kind` is lowercase-normalized via `_normalize_edge_kind` and must match `[a-z0-9_.-]+`, 1-64 characters. Also DB-enforced via `CHECK (kind GLOB '[a-z0-9_.-]*' AND length(kind) BETWEEN 1 AND 64)`.
- **Duplicate active names** for workspaces, statuses, tasks, and groups
  are rejected with entity-specific messages (via error translation).

## Archival Safety (service-only)

The database does not distinguish between active and archived rows for foreign key
or mutation purposes. These rules exist only in the service layer.

### Referencing archived entities is forbidden

Active entities cannot point to archived parents:

- **A task cannot be moved to an archived status.**
- **A task cannot be assigned to an archived group.**
- **An edge cannot be created between archived tasks.** `add_task_edge` raises `ValueError` if either endpoint is archived. Symmetric rule for `add_group_edge`.

### Cascade archive

Archiving a parent entity cascades to all its active descendants:

- **Archiving a group** cascade-archives all descendant groups and tasks in the subtree.
- **Archiving a workspace** cascade-archives all tasks, groups, and statuses.
- **Archiving a status** either reassigns active tasks to another status, force-archives
  them, or blocks if neither option is specified.

### Mutations on archived entities are allowed

Editing or otherwise mutating an archived entity is permitted — except for
adding edges (see the archived-endpoint rule above). This supports fixing
metadata before unarchiving.

## Cross-Workspace Move Preconditions (service-only)

- **An archived task cannot be moved to another workspace.**
- **A task with active edges cannot be moved to another workspace.** Archive all
  edges (both directions) first via `stx edge archive`.
- **The target status must belong to the target workspace.**
- **The target status must not be archived.**

### Cross-workspace move side effects

A cross-workspace move creates a new task on the target workspace and archives the
original. Carried over:

- **Metadata** — copied verbatim via `repo.copy_task_metadata` (one-shot
  JSON-blob copy; keys retain their lowercase-normalized form).

NOT carried over:

- **group_id** — groups are workspace-scoped and the target workspace has its own group hierarchy; the new task starts ungrouped.
- **History** — the original task retains its history; the new task starts fresh.

## Automatic Behaviors (service-only)

- **`assign_task_to_group` validates same-workspace** and writes `group_id`. `update_task` accepts `group_id` directly; `assign_task_to_group` and `unassign_task_from_group` are thin wrappers over `update_task` (via `_update_task_body` so they can hold their own outer transaction without tripping the nesting guard).

## Entity Metadata (service-only)

Tasks, workspaces, and groups each carry an independent JSON
key/value metadata blob, enforced identically at the service layer via
generic helpers (`_set_entity_meta` / `_get_entity_meta` / `_remove_entity_meta`
/ `_replace_entity_metadata`) that are called by per-entity one-line delegates.

- **Metadata keys are normalized to lowercase** on write, read, and removal
  (`_normalize_meta_key()`). This matches the codebase's case-insensitive naming
  convention (`COLLATE NOCASE`), which can't be applied directly to JSON keys.
- **Key charset:** `[a-z0-9_.-]+` after normalization; max 64 characters.
- **Value length cap:** 500 characters. Values are otherwise free-form text.
- **Keys are stored lowercase:** `meta set X Branch feat/kv` and
  `meta get X BRANCH` resolve to the same entry on any entity.
- **Removing a missing key raises `LookupError`** with a "not found" message.
- **Cross-workspace move preserves task metadata** — copied verbatim via
  `repo.copy_task_metadata` as part of `move_task_to_workspace`. Workspace
  and group metadata is scoped to those entities and does not
  participate in cross-workspace task moves.
- **Two write surfaces, same normalization rules.** Per-key writes go through
  `set_*_meta` / `remove_*_meta` (one key at a time, used by the CLI); bulk
  writes go through `replace_*_metadata` (the whole dict at once, used by the
  TUI `MetadataModal` to atomically apply multi-row edits). The bulk path
  walks every pair through `_normalize_meta_key`, rejects duplicate keys
  post-normalization, enforces the 500-char value cap, then writes a
  `json.dumps()`-ed blob in a single UPDATE.
- **Metadata changes ARE recorded in the `journal` table** (as of 0.11.0). Both
  the per-key and bulk-replace code paths emit `journal` rows with `field` set
  to `meta.<key>` and the old/new values filled in. The `source` parameter is
  propagated through all delegates and recorded on the journal entry.
- **Edges also carry metadata.** The unified polymorphic `edges` table has its
  own `metadata` JSON column with identical rules (lowercase-normalized keys,
  `[a-z0-9_.-]+` charset, 64-char key cap, 500-char value cap). Access via
  `stx edge meta ls|get|set|del --source <ref> --target <ref> --kind <k>`.
  Repository-level helpers operate on the composite `(from_type, from_id,
  to_type, to_id, kind)` key rather than the single-id `_METADATA_TABLES`
  allowlist used by tasks/workspaces/groups. Edge metadata mutations emit
  `meta.<key>` journal rows with `entity_type = edge` and endpoints encoded
  on the `endpoint` field as `"<from_type>:<from_id>→<to_type>:<to_id>"`.

## Audit Trail (service-only logic, DB-enforced schema)

- **Task field changes are recorded as history entries** when a value actually
  changes (no-op updates are skipped). The set of trackable fields is fixed by
  the `TaskField` enum: title, description, status, priority, due date,
  archived, start date, finish date, group.
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
| `UNIQUE constraint failed: statuses.*` | "a status with this name already exists on this workspace" |
| `UNIQUE constraint failed: groups.*` | "a group with this title already exists here" |
| `UNIQUE constraint failed: tasks.*` | "a task with this title already exists on this workspace" |
| `UNIQUE constraint failed: task_edges.*` / `group_edges.*` | "an edge already exists between these entities" |
| `CHECK constraint failed: task_edges.*` / `group_edges.*` | "edge kind must match [a-z0-9_.-]+ and be 1-64 characters" |
| `FOREIGN KEY constraint failed` | context-specific or generic FK message |
