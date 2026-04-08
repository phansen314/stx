# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A local todo/kanban app (`todo` CLI) with two interfaces: CLI (argparse) and TUI (Textual), backed by SQLite storage. All layers are fully implemented. Use `--json` flag for structured CLI output. See `skills/sticky-notes/references/cli-reference.md` for the full CLI reference.

## Architecture

```
CLI commands ────────┐
TUI event handlers ──┤──▶ Service ──▶ Repository ──▶ Connection ──▶ SQLite
```

**Data hierarchy:** Workspace → Status → Task (and Workspace → Project → Task, Workspace → Tag ↔ Task). Statuses are workspace-scoped and represent kanban workflow stages. No data is ever deleted — use `archived` flags instead.

## Project Structure

```
src/sticky_notes/
  __main__.py        # entry point (todo command)
  cli.py             # argparse CLI — thin controllers: parse args, delegate to service, hand payloads to presenters
  presenters.py      # pure functions: structured types → text. No DB access.
  formatting.py      # shared formatting primitives: format_task_num, format_priority, parse_date, format_timestamp
  active_workspace.py# read/write active workspace ID to disk
  service.py         # business logic, transaction boundaries
  repository.py      # raw SQL queries, one function per operation
  connection.py      # SQLite connection factory, schema init, migration runner
  models.py          # domain dataclasses (New*, persisted)
  service_models.py  # Ref/ListItem/Detail dataclasses + view aggregates (WorkspaceListView, WorkspaceContext)
  mappers.py         # row→model, model→ref, ref→listitem, ref→detail converters
  export.py          # full-database Markdown + Mermaid export
  schema.sql         # DDL (current schema, used for fresh databases)
  migrations/        # numbered SQL migration files (001_*.sql ... 006_*.sql)
  tui/
    app.py           # StickyNotesApp — main Textual app, two-panel layout, keybindings, modal dispatch
    model.py         # WorkspaceModel — loads workspace hierarchy via service, builds tree
    config.py        # TuiConfig dataclass, TOML load/save
    markup.py        # escape_markup helper for Textual rendering
    sticky_notes.tcss# global stylesheet
    screens/
      __init__.py      # re-exports all modals
      base_edit.py     # BaseEditModal, ModalScroll — shared form scaffolding
      task_edit.py     # TaskEditModal
      task_create.py   # TaskCreateModal
      project_edit.py  # ProjectEditModal
      project_create.py# ProjectCreateModal
      group_edit.py    # GroupEditModal
      group_create.py  # GroupCreateModal
      workspace_edit.py    # WorkspaceEditModal
      workspace_switch.py  # WorkspaceSwitchModal
      new_resource.py  # NewResourceModal — Alt+N resource type selector
    widgets/
      __init__.py        # re-exports widgets
      workspace_tree.py  # WorkspaceTree — left-panel tree widget
      kanban_board.py    # KanbanBoard — right-panel kanban with diff-based sync
      task_card.py       # TaskCard — focusable card widget
      markdown_editor.py # MarkdownEditor — edit/preview toggle for description fields

tests/
  conftest.py            # fixtures (fresh DB, seeded workspace/statuses/tasks)
  helpers.py             # raw SQL insert helpers + ModalTestApp harness
  seed.py                # seed_workspace() for TUI test fixtures and manual testing
  test_cli.py            # CLI integration tests
  test_connection.py
  test_export.py
  test_mappers.py
  test_presenters.py     # pure-function tests for text rendering (DB-free)
  test_repository.py
  test_service.py
  test_tui.py            # TUI tests: tree population, no-workspace handling, grouped/nested tree rendering
  test_tui_model.py      # WorkspaceModel tests: tree building, archived filtering, unassigned tasks
  test_task_edit_modal.py    # task edit modal tests
  test_edit_modals.py        # project, group, workspace edit modal tests
  test_create_modals.py      # create modal + resource selector tests
  test_markdown_editor.py    # markdown editor widget tests
```

## CLI

Entry point: `todo = "sticky_notes.__main__:main"`.

**Active workspace:** persisted at `~/.local/share/sticky-notes/active-workspace`. CLI resolves workspace from `--workspace`/`-w` flag, falling back to this file. Set via `todo workspace create` or `todo workspace use`.

**Command structure:**
- Task subcommands: `todo task create|ls|show|edit|mv|transfer|rm|log`
- Other subcommand groups: `workspace`, `status`, `project`, `dep`, `group-dep`, `group`, `tag`
- Standalone commands: `context`, `export`, `info`, `backup`

## TUI

Entry point: `todo tui` (or `todo tui --db path/to/db`).

**Architecture:**
- **Model** (`tui/model.py`): `WorkspaceModel` loads all non-archived data for the active workspace via existing service functions, then organizes it into a tree: `WorkspaceModel` → `ProjectNode` → `GroupNode` (recursive). Tasks without a project live in `unassigned_tasks`. Groups nest recursively via `parent_id`. Dependency-aware topological ordering for both tree and kanban.
- **View / Controller** (`tui/app.py`): `StickyNotesApp` — two-panel layout. Left: `#workspaces-panel` (25% width) with `WorkspaceTree`. Right: `#kanban-panel` with `KanbanBoard` — one scrollable column per status with `TaskCard` widgets. Diff-based kanban sync with coalescing refresh (duplicates merge in the message queue). `app.py` acts as both view and controller — dispatches keybindings, pushes modals, calls service layer on dismiss.
- **Screens**: `BaseEditModal` provides shared form scaffolding: save/cancel buttons, error display, field navigation (`ctrl+n`/`ctrl+b`), date parsing (`_parse_date_field`), change diffing (`_diff_and_dismiss`). Edit modals diff form values against the original entity and dismiss with changes only. Create modals dismiss with the full form data dict. `_dismiss_callback` in `app.py` wraps the common null-check → try/except → notify → refresh pattern for all modal callbacks.
- **Widgets**: `WorkspaceTree` (tree with emoji prefixes: workspace, project, group, task — node `data` carries the model object), `KanbanBoard` (diff-based card sync, status-move via alt+j/alt+l), `TaskCard` (focusable, renders task summary), `MarkdownEditor` (edit/preview toggle for description fields).

**Keybindings:**
| Key | Action |
|-----|--------|
| `alt+w` | Focus workspace tree |
| `alt+b` | Focus kanban board |
| `r` | Refresh |
| `e` | Edit selected entity |
| `alt+n` | Create new (task/group/project selector) |
| `s` | Switch workspace |
| `alt+j` / `alt+l` | Move task left/right across statuses |
| `ctrl+q` | Quit |

**Config:** `~/.config/sticky-notes/tui.toml` — theme, show_archived, confirm_archive, default_priority, status_order, auto_refresh_seconds. Loaded via `TuiConfig` dataclass in `tui/config.py`.

## Key Design Conventions

- **Separate pre-insert and persisted types** — `NewTask` (no `id`/`created_at`) vs `Task` (full row). Never use `None` as a stand-in for "not yet assigned."
- **ListItem vs Detail service models** — two tiers of denormalization for tasks. `TaskListItem` is a flat dataclass of Task fields plus resolved display names (`project_name`, `tag_names`) for list rendering without per-row lookups. `TaskDetail` is a flat dataclass of Task fields plus fully hydrated relationships (`status`, `project`, `group`, `blocked_by`, `blocks`, `history`, `tags`) for single-entity views. Both redeclare Task fields directly — they do not inherit from `Task`. `GroupRef` is the only surviving Ref type, used by `build_group_tree` / `GroupTreeNode` to walk the hierarchy without hydrating every group. `WorkspaceListView` is the aggregate view model for `cmd_ls` — workspace + ordered statuses + TaskListItems. `WorkspaceContext` is the aggregate view model for `cmd_context` — `WorkspaceListView` + projects + tags + groups, for one-call AI session startup.
- **All dataclasses are frozen** — immutability throughout. Changes produce new instances via DB.
- **Defaults on pre-insert dataclasses** — optional/defaultable fields on `New*` types carry defaults directly. No factory layer needed.
- **Service models are flat, not inherited** — `TaskListItem`, `TaskDetail`, `ProjectDetail`, and `GroupDetail` redeclare their parent entity's fields rather than inheriting from `Task` / `Project` / `Group`. Tradeoff: adding a column to `tasks` touches both `TaskListItem` and `TaskDetail` in addition to `Task` and `row_to_task`. The win is that hydrated fields can be plain required annotations (e.g. `status: Status` on `TaskDetail`) without dataclass field-ordering gymnastics. An earlier inheritance-based version required `status: Status = None  # type: ignore` with a runtime `__post_init__` check — flat redeclaration removes that hack.
- **Mappers are plain functions** — explicit conversion at each layer boundary (row→model, model→ref, ref→detail). Models are pure data containers with no methods — conversion logic stays in `mappers.py`, not as classmethods. Accept the boilerplate to keep separation clean.
- **`shallow_fields()` helper** — extracts a dataclass's fields as a dict for splatting into derived types (`TaskListItem`, `TaskDetail`, `GroupRef`, etc.). Lives in `mappers.py`.
- **Repository update allowlists** — each entity has a `_*_UPDATABLE` frozenset guarding which fields can be passed to update functions.
- **Task history / audit trail** — `_record_changes()` in the service layer auto-records `TaskHistory` entries for changed fields. `TaskField` enum defines trackable fields.
- **Transaction context manager** — service layer controls transaction boundaries. Repository functions receive a connection and never commit/rollback. On rollback failure, `raise exc from rollback_exc` — the original error is primary, rollback failure is attached as `__cause__`. This is intentional.
- **Timestamps as Unix epoch integers** — formatting happens at the edges only. `parse_date` and `format_timestamp` live in `formatting.py` (shared by CLI and TUI).
- **Task numbers** — formatted as `task-{id:04d}` in the application layer, derived from autoincrement ID. `format_task_num` and `format_priority` also live in `formatting.py`.
- **Active workspace file** — persisted at `~/.local/share/sticky-notes/active-workspace`. CLI resolves workspace from `--workspace` flag or this file.
- **Tags** — workspace-scoped, many-to-many with tasks via `task_tags` junction table. `tag_task` auto-creates the tag if it doesn't exist. Composite FKs enforce same-workspace scoping at the DB level.
- **Error translation** — `_friendly_errors()` context manager in the service layer catches `IntegrityError` and translates to `ValueError` with human-readable messages. `_UNIQUE_MESSAGES` dict maps constraint patterns to messages.
- **Service-layer pre-validation** — `_validate_task_fields()` checks scalar constraints (priority range, position >= 0, date ordering) and cross-entity constraints (status/project exists, on correct workspace, not archived) before hitting the DB.
- **Migrations** — numbered SQL files in `src/sticky_notes/migrations/` (e.g., `004_column_to_status.sql`). `_run_migrations()` discovers files by version prefix, wraps each in FK-off + transaction + FK-revalidate. SQL files contain only DDL/DML — no PRAGMAs, no transaction control. `SCHEMA_VERSION` is explicit; a test asserts it matches the highest migration file number. Fresh databases skip migrations entirely (`init_db` runs `schema.sql` and stamps `SCHEMA_VERSION`). When recreating tables with FK deps (e.g. `tasks`), cascade-recreate dependent tables (`task_dependencies`, `task_tags`, `task_history`); use `CASE` in INSERT to transform field values rather than UPDATE before recreate (avoids violating the old CHECK constraint). Note: `task_history` must be recreated whenever `tasks` is renamed, because SQLite automatically redirects its FK reference to the renamed table.
- **BaseEditModal pattern** — shared TUI modal base class providing save/cancel buttons, error display, `ctrl+n`/`ctrl+b` field navigation, `_do_save` (subclass hook), `_diff_and_dismiss` (edit modals), and `_parse_date_field` (date input validation). `_dismiss_callback` on `StickyNotesApp` wraps the null-check → try/except ValueError → notify → refresh pattern used by all modal callbacks.
- **Export** — `export.py` renders the full database to Markdown with Mermaid dependency graphs.
- **DB path** — `~/.local/share/sticky-notes/sticky-notes.db` (XDG-compliant).
- **WAL journal mode** — enables concurrent reads from TUI and CLI.

## Testing

- **pytest** with `pytest-cov`; fixtures in `conftest.py`, raw SQL insert helpers in `tests/helpers.py`
- Fresh in-memory DB per test — no cross-test pollution
- Test files cover all layers: connection, repository, service, mappers, export, CLI, TUI
- TUI tests use Textual's `app.run_test()` pilot API with `seeded_tui_db` fixture (from `tests/seed.py`)
- `seed.py` also runnable standalone: `python tests/seed.py tmp/test.db` for manual smoke testing

## Python

- Python 3.12+ (uses `type` statement for type aliases, `str | None` union syntax)
- Build system: hatchling
- Dependencies: textual
- Dev dependencies: pytest, pytest-cov
