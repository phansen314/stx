# Database Business Rules

Business rules enforced by the schema. These hold regardless of which
interface (CLI, TUI) or code path is used.

---

## Ownership & Scoping

- **Boards are the top-level container.** Everything — columns, projects, tasks, tags — belongs to exactly one board.
- **A task cannot reference entities from a different board.** Its column, project, and tags must all belong to the same board as the task itself.
- **A group belongs to exactly one project.** A task's group must belong to the same project as the task.
- **A task can exist without a project or group**, but a task in a group must also be in a project.

## Naming & Identity

- **Names and titles are case-insensitive.** "Backlog" and "backlog" are treated as the same name everywhere — lookups, sorting, and uniqueness checks.
- **Active names must be unique within their scope:**
  - Board names are globally unique
  - Project, column, tag, and task names are unique per board
  - Group titles are unique per project
- **Archiving frees the name.** Uniqueness only applies to active (non-archived) rows. Multiple archived rows can share a name, and archiving a row allows creating a new active row with the same name.

## Tasks

- **Every task must be in a column.** There is no "uncolumned" state.
- **Priority is an integer from 1 to 5** (defaults to 1).
- **Position is a non-negative integer** (defaults to 0). Same applies to columns and groups.
- **If both start and finish dates are set, finish must be on or after start.**
- **A task cannot depend on itself.**
- **A dependency relationship between two tasks is unique** — you cannot create the same dependency twice.

## Tags

- **Tags and tasks have a many-to-many relationship.** A task can have multiple tags; a tag can apply to multiple tasks.
- **A tag can only be applied to tasks on the same board.**
- **Each tag is applied to a task at most once** (no duplicate tagging).

## Groups

- **Groups form a hierarchy.** A group can have a parent group, and the parent must belong to the same project. Enforced by a composite FK: `(parent_id, project_id)` → `groups(id, project_id)`.
- **A group with children cannot be hard-deleted.** The composite FK is `ON DELETE RESTRICT`. The application archives groups instead; `archive_group` manually reparents children before archiving.

## Deletion & Archival

- **You cannot delete a board that has projects, columns, or tasks.** Same for projects with groups, columns with tasks, and groups with child groups — the database blocks it with `ON DELETE RESTRICT`.
- **Removing a task cascades to its junction data:** tag associations, dependencies, and history records are cleaned up automatically (`ON DELETE CASCADE`).

*Note: The convention of never hard-deleting entities (using `archived` instead) is enforced by the application, not the schema. The schema permits direct `DELETE` statements.*

## Audit Trail

- **The set of trackable task fields is fixed** by a `CHECK` constraint on `task_history.field`: title, description, column, project, priority, due date, position, archived status, start date, finish date, and group. Entries with any other field name are rejected.
- **Each history entry records the old value, new value, and source** (who/what made the change). `old_value` and `new_value` are nullable (e.g., `old_value` is NULL on first assignment).

*Note: Recording of changes is done by the service layer, not the database. The DB provides the schema and validates field values but does not auto-generate history rows.*

## Timestamps

- **Creation timestamps are set automatically by the database** (Unix epoch). Application code does not provide them.
- **History change timestamps are also set automatically.**
