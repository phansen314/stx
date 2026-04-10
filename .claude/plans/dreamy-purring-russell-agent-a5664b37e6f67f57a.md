# TUI Model Module — Implementation Plan

## Overview

Create `src/sticky_notes/tui/model.py` containing:
1. `NavTask` — lightweight frozen dataclass (Task minus `description`)
2. `WorkspaceModel` — frozen dataclass aggregating all workspace data
3. `row_to_nav_task()` — mapper function for the custom SQL query
4. `load_workspace_model()` — loader function that hydrates the entire model

Also create `tests/test_tui_model.py` with full test coverage.

---

## Design Decisions (Answers to the Four Questions)

### Q1: Where does the custom task query live?

**Answer: In `tui/model.py`, not `repository.py`.**

Rationale:
- The repository layer uses `SELECT *` universally and maps through `row_to_task`. Adding a description-excluding query there creates a precedent for projection-specific queries in a layer that has been projection-agnostic.
- If we put the query in `repository.py`, we'd also need to either (a) put `NavTask` in `models.py` and `row_to_nav_task` in `mappers.py`, polluting the shared domain layer with a TUI-specific optimization, or (b) have `repository.py` return raw `sqlite3.Row` objects, breaking its contract of always returning typed domain objects.
- The `tui/model.py` module already imports `repository` for the other four queries — having one additional direct SQL call is a contained, self-documenting exception. A comment explains why.
- This mirrors how `service.py` contains `list_tasks_filtered` with its own dynamic SQL — layer-specific query shaping is acceptable when the caller has a unique data need.

### Q2: Should `unassigned_tasks` be a separate field?

**Answer: Yes, store as a separate tuple field on `WorkspaceModel`.**

Rationale:
- The nav panel and board have fundamentally different rendering paths for unassigned tasks (they appear as a separate "Unassigned" node in the workspace tree, not under any project). Making this a first-class field makes the boundary explicit.
- Computing it is trivial at load time (single pass filter) and avoids every consumer repeating `[t for t in model.tasks if t.project_id is None]`.
- The `tasks` field contains ALL tasks (including unassigned). This means `unassigned_tasks` is a derived subset, not a partition. The alternative (partitioning into assigned + unassigned) would complicate consumers that need "all tasks for status X" regardless of assignment. Keeping `tasks` as the complete set is cleaner.

### Q3: Should `load_workspace_model` raise `LookupError`?

**Answer: Yes, raise `LookupError` if workspace not found.**

Rationale:
- The service layer consistently uses `LookupError` for "entity not found" (see `get_workspace`, `get_task`, `get_status`, `get_project`, `get_group` in `service.py` — all raise `LookupError`).
- The caller (TUI app) needs a clear signal to show an error screen or prompt workspace selection. A `None` return forces every caller to check; an exception is the established pattern.
- The message format follows the existing convention: `f"workspace {workspace_id} not found"`.

### Q4: Should `WorkspaceModel` include index structures?

**Answer: No index structures in the model. The view builds those.**

Rationale:
- `WorkspaceModel` is a *data container*, not a query engine. Adding `tasks_by_status: dict[int, tuple[NavTask, ...]]` couples the model to specific view layout decisions.
- The board widget knows its column layout (status ordering from config). The nav tree knows its hierarchy. Each can build the index it needs in one pass over `model.tasks`.
- Frozen dicts aren't ergonomic in Python. We'd need `MappingProxyType` or `tuple` of pairs, adding complexity for no gain.
- If profiling later shows the view is doing redundant passes, we can add a cached property or helper function — but that's optimization, not initial design.

---

## File 1: `src/sticky_notes/tui/model.py`

### Imports

```python
from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from sticky_notes import repository as repo
from sticky_notes.models import Group, Project, Status, Workspace
```

Note: Uses absolute imports (`from sticky_notes...`) not relative (`from ..`), matching `tui/__init__.py` and `tui/app.py` which both use `from sticky_notes.connection import ...` style.

### `NavTask` dataclass

```python
@dataclass(frozen=True)
class NavTask:
    """Lightweight task for TUI navigation — all Task fields except description."""
    id: int
    workspace_id: int
    title: str
    project_id: int | None
    status_id: int
    priority: int
    due_date: int | None
    position: int
    archived: bool
    created_at: int
    start_date: int | None
    finish_date: int | None
    group_id: int | None
```

Key points:
- Frozen, matching project convention.
- Field order matches `Task` field order with `description` removed. This is deliberate — when reading the two side by side, missing fields are visually obvious.
- 13 fields (Task has 14). The excluded `description` is the 5th field in `Task`.
- Uses `int | None` union syntax (Python 3.12+), matching project convention.

### `row_to_nav_task` mapper

```python
def row_to_nav_task(row: sqlite3.Row) -> NavTask:
    """Map a tasks row (without description) to NavTask."""
    return NavTask(
        id=row["id"],
        workspace_id=row["workspace_id"],
        title=row["title"],
        project_id=row["project_id"],
        status_id=row["status_id"],
        priority=row["priority"],
        due_date=row["due_date"],
        position=row["position"],
        archived=bool(row["archived"]),
        created_at=row["created_at"],
        start_date=row["start_date"],
        finish_date=row["finish_date"],
        group_id=row["group_id"],
    )
```

Key points:
- Lives in `tui/model.py`, not `mappers.py`, because `NavTask` is TUI-specific.
- Uses explicit field-by-field mapping like all other `row_to_*` functions in `mappers.py` — no `**dict` unpacking.
- `bool(row["archived"])` matches the pattern in every existing mapper (archived is stored as INTEGER 0/1 in SQLite).

### `WorkspaceModel` dataclass

```python
@dataclass(frozen=True)
class WorkspaceModel:
    """All active data for a single workspace — the TUI's read model."""
    workspace: Workspace
    statuses: tuple[Status, ...]
    projects: tuple[Project, ...]
    groups: tuple[Group, ...]
    tasks: tuple[NavTask, ...]
    unassigned_tasks: tuple[NavTask, ...]
```

Key points:
- All tuple types, matching the project's convention for immutable collections (see `service_models.py` — every collection field is `tuple[T, ...]`).
- `tasks` is the complete set. `unassigned_tasks` is the subset with `project_id is None`.
- Uses domain types directly (`Status`, `Project`, `Group`) — no re-declaration of fields like `TaskListItem` does, because these entities are used as-is.

### `load_workspace_model` function

```python
_NAV_TASK_COLUMNS = (
    "id, workspace_id, title, project_id, status_id, priority, "
    "due_date, position, archived, created_at, start_date, finish_date, group_id"
)


def load_workspace_model(
    conn: sqlite3.Connection,
    workspace_id: int,
) -> WorkspaceModel:
    """Load all active data for a workspace into an immutable model.

    Raises LookupError if the workspace does not exist.
    """
    workspace = repo.get_workspace(conn, workspace_id)
    if workspace is None:
        raise LookupError(f"workspace {workspace_id} not found")

    statuses = repo.list_statuses(conn, workspace_id)
    projects = repo.list_projects(conn, workspace_id)
    groups = repo.list_groups_by_workspace(conn, workspace_id)

    # Custom query: exclude description for memory efficiency.
    # This is the only TUI-specific SQL — all other queries delegate to
    # repository.py.  Kept here because NavTask is a TUI-local type.
    rows = conn.execute(
        f"SELECT {_NAV_TASK_COLUMNS} FROM tasks "
        "WHERE workspace_id = ? AND archived = 0 "
        "ORDER BY position, id",
        (workspace_id,),
    ).fetchall()
    tasks = tuple(row_to_nav_task(r) for r in rows)

    unassigned_tasks = tuple(t for t in tasks if t.project_id is None)

    return WorkspaceModel(
        workspace=workspace,
        statuses=statuses,
        projects=projects,
        groups=groups,
        tasks=tasks,
        unassigned_tasks=unassigned_tasks,
    )
```

Key points:
- Column list is a module-level constant `_NAV_TASK_COLUMNS` — if the tasks schema changes, updating this constant (and `NavTask`) is the single point of change within the TUI layer.
- `ORDER BY position, id` matches `repo.list_tasks()` exactly.
- `archived = 0` is hardcoded (not parameterized via `include_archived`) because the model's contract is "active data only." The existing repo functions default to `include_archived=False` which also filters `archived = 0`.
- The repo calls for statuses/projects/groups all default to `include_archived=False`, so non-archived filtering is consistent across all entity types.
- `LookupError` with the standard message format.

### Why not use `shallow_fields` + Task?

An alternative would be: call `repo.list_tasks()` (which returns full `Task`), then use `shallow_fields(task, Task)` to extract fields and drop `description`. This avoids custom SQL but:
1. Fetches `description` from SQLite only to discard it — defeats the memory optimization purpose.
2. Requires building a dict per task and splatting into `NavTask` — slower than direct row mapping.
3. The whole point of `NavTask` is to never load `description` into Python memory.

---

## File 2: `tests/test_tui_model.py`

### Test structure

```
tests/test_tui_model.py
    TestNavTask
        test_is_frozen
        test_fields_match_task_minus_description
        test_has_no_description_field
    TestRowToNavTask
        test_maps_row
        test_archived_is_bool
        test_null_optional_fields
    TestWorkspaceModel
        test_is_frozen
    TestLoadWorkspaceModel
        test_loads_workspace
        test_loads_statuses
        test_loads_projects
        test_loads_groups
        test_loads_tasks_without_description
        test_tasks_ordered_by_position
        test_unassigned_tasks_have_no_project
        test_unassigned_tasks_is_subset_of_tasks
        test_excludes_archived_tasks
        test_excludes_archived_statuses
        test_excludes_archived_projects
        test_raises_lookup_error_for_missing_workspace
```

### Test conventions

Following existing patterns from `test_mappers.py` and `test_repository.py`:
- Uses the `conn` fixture from `conftest.py` (fresh in-memory DB per test).
- Uses raw SQL helpers from `tests/helpers.py` (`insert_workspace`, `insert_status`, `insert_project`, `insert_task`, `insert_group`).
- Uses `transaction(conn)` context manager for setup.
- Each test class groups related assertions.
- `dataclasses.fields()` used for structural assertions (matching `TestShallowFields` and `TestPersistedTaskFieldsMatchSchema` patterns).

### Key test details

**`test_fields_match_task_minus_description`**: Verify that `set(NavTask field names) == set(Task field names) - {"description"}`. This is a schema-drift guard — if someone adds a field to `Task`, this test will fail, reminding them to add it to `NavTask` (or explicitly exclude it).

**`test_loads_tasks_without_description`**: Insert a task with a description via `insert_task` helper (or raw SQL to set description), then load the model and verify the resulting `NavTask` has no `description` attribute.

**`test_unassigned_tasks_is_subset_of_tasks`**: Verify `set(model.unassigned_tasks) <= set(model.tasks)` and every entry has `project_id is None`.

**`test_excludes_archived_tasks`**: Insert a task, archive it via raw SQL, load the model, assert the task is absent.

**`test_raises_lookup_error_for_missing_workspace`**: `pytest.raises(LookupError, match="workspace 9999 not found")`.

---

## Implementation Sequence

1. **Create `src/sticky_notes/tui/model.py`**
   - `NavTask` dataclass
   - `row_to_nav_task()` function
   - `WorkspaceModel` dataclass
   - `_NAV_TASK_COLUMNS` constant
   - `load_workspace_model()` function

2. **Create `tests/test_tui_model.py`**
   - All test classes listed above
   - Note: `insert_task` helper in `tests/helpers.py` doesn't set `description` — for the description-exclusion test, use raw SQL: `conn.execute("UPDATE tasks SET description = 'some text' WHERE id = ?", (task_id,))`

3. **Run tests to verify**
   - `python -m pytest tests/test_tui_model.py -v`

No changes needed to any existing files. This module is entirely additive.

---

## Risks and Mitigations

| Risk | Mitigation |
|------|-----------|
| `_NAV_TASK_COLUMNS` drifts from schema | `test_fields_match_task_minus_description` catches this — if a column is added to `tasks` and `Task`, the test fails |
| Custom SQL bypasses repository patterns | Contained to one query, documented with comment, and the alternative (fetching description to discard it) defeats the purpose |
| `WorkspaceModel` missing data the view needs later | Model carries the full entity objects (Status, Project, Group) — any field on those is available. For tasks, only `description` is excluded, and that's loaded on-demand via `TaskDetailModal` |
| `unassigned_tasks` redundancy with `tasks` | Tuple of references, not copies — negligible memory cost. Eliminates repeated filtering in every consumer |

---

## What This Module Does NOT Do

- No integration with the Textual app or widgets (that's the next step)
- No index structures (tasks_by_status, etc.) — the view layer builds those
- No caching or invalidation — each call to `load_workspace_model` is a fresh snapshot
- No write operations — this is a read model only
