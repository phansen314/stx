# Database Business Rules

Business rules enforced by the schema. These hold regardless of which
interface (CLI, TUI) or code path is used.

---

## Ownership & Scoping

- **Workspaces are the top-level container.** Everything — statuses, groups, tasks, tags — belongs to exactly one workspace.
- **A task cannot reference entities from a different workspace.** Its status and tags must all belong to the same workspace as the task itself.
- **A task can exist without a group; assignment is optional.**

## Naming & Identity

- **Names and titles are case-insensitive.** "Backlog" and "backlog" are treated as the same name everywhere — lookups, sorting, and uniqueness checks.
- **Active names must be unique within their scope:**
  - Workspace names are globally unique
  - Status, tag, and task names are unique per workspace
  - Group titles are unique per (workspace, parent) — root groups are unique per workspace; nested groups are unique within their parent
- **Archiving frees the name.** Uniqueness only applies to active (non-archived) rows. Multiple archived rows can share a name, and archiving a row allows creating a new active row with the same name.

## Tasks

- **Every task must be in a status.** There is no "unstatused" state.
- **Priority is an integer from 1 to 5** (defaults to 1).
- **Position is a non-negative integer** (defaults to 0). Same applies to statuses and groups.
- **If both start and finish dates are set, finish must be on or after start.**
- **A task cannot reference itself in an edge.** Enforced by `CHECK (source_id != target_id)` on `task_edges`.
- **An edge between two tasks is unique across all kinds.** The PK is `(source_id, target_id)` on `task_edges`, so a second edge between the same pair is rejected regardless of `kind`.
- **Task metadata is a JSON object.** The `tasks.metadata` column has `CHECK (json_valid(metadata))` and defaults to `'{}'`. The schema does not constrain keys or values beyond valid JSON — key normalization and length limits are enforced by the service layer. The same JSON-blob metadata column exists on `workspaces` and `groups` with identical constraints.

## Tags

- **Tags and tasks have a many-to-many relationship.** A task can have multiple tags; a tag can apply to multiple tasks.
- **A tag can only be applied to tasks on the same workspace.**
- **Each tag is applied to a task at most once** (no duplicate tagging).

## Groups

- **Groups form a hierarchy.** A group can have a parent group, and the parent must belong to the same workspace. Enforced by a composite FK: `(parent_id, workspace_id)` → `groups(id, workspace_id)`. Root-group uniqueness uses `COALESCE(parent_id, -1)` to handle SQLite's NULL-in-unique pitfall.
- **A group with children cannot be hard-deleted.** The composite FK is `ON DELETE RESTRICT`. The application archives groups instead; cascade archive archives all descendant groups and their tasks.
- **Group edges are workspace-scoped via composite FK.** `group_edges.(source_id, workspace_id)` and `(target_id, workspace_id)` reference `groups(id, workspace_id)`, mirroring how `task_edges` anchors to `tasks(id, workspace_id)`. Cross-workspace group edges are rejected at the DB layer, not just the service.

## Deletion & Archival

- **You cannot delete a workspace that has groups, statuses, or tasks.** Same for groups with child groups or tasks, and statuses with tasks — the database blocks it with `ON DELETE RESTRICT`.
- **Deleting a task cascades to its junction data:** tag associations and edges are cleaned up automatically (`ON DELETE CASCADE`). Journal entries persist (they belong to the workspace, not the task).
- **Edges are soft-archived, not deleted.** `task_edges` and `group_edges` have an `archived` column. Archiving an edge sets `archived = 1`; all active queries filter on `archived = 0`. There is no unarchive CLI surface — re-creating an archived edge via `stx edge create` clears its metadata blob and flips `archived = 0` (a journal entry records the flip).

*Note: The convention of never hard-deleting entities (using `archived` instead) is enforced by the application, not the schema. The schema permits direct `DELETE` statements.*

## Audit Trail

- **Audit trail lives in the unified `journal` table.** One row per tracked change across all entity types. `entity_type` is constrained by CHECK to `{task, group, workspace, status, task_edge, group_edge}`. `field` is an unconstrained TEXT column — field enums (`TaskField`, `EdgeField`, etc.) exist in `models.py` for documentation and service-layer validation, not DB enforcement.
- **Each journal entry records old value, new value, and source** (who/what made the change). `old_value` and `new_value` are nullable (e.g., `old_value` is NULL on first assignment). Metadata mutations are recorded with field `meta.<key>`.

*Note: Recording of changes is done by the service layer, not the database. The DB provides the schema and validates entity_type values but does not auto-generate journal rows.*

## Timestamps

- **Creation timestamps are set automatically by the database** (Unix epoch). Application code does not provide them.
- **History change timestamps are also set automatically.**
