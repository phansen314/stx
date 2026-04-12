# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A structured context and task management app (`stx` CLI) with two interfaces: CLI (argparse) and TUI (Textual), backed by SQLite storage. All layers are fully implemented. CLI auto-emits JSON when piped and text at a terminal (`--json`/`--text` override). See `skills/stx/references/cli-reference.md` for the full CLI reference and `skills/stx/references/json-schema.md` for JSON shapes.

## Architecture

```
CLI commands ────────┐
TUI event handlers ──┤──▶ Service ──▶ Repository ──▶ Connection ──▶ SQLite
```

**Data hierarchy:** Workspace → Status → Task (and Workspace → Project → Task, Workspace → Tag ↔ Task). Statuses are workspace-scoped and represent kanban workflow stages. No data is ever deleted — use `archived` flags instead.

## Project Structure

```
src/stx/
  __main__.py        # entry point (stx command)
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
  migrations/        # numbered SQL migration files (001_*.sql ... 012_*.sql)
  tui/
    app.py           # StxApp — main Textual app, two-panel layout, keybindings, modal dispatch
    model.py         # WorkspaceModel — loads workspace hierarchy via service, builds tree
    config.py        # TuiConfig dataclass, TOML load/save
    markup.py        # escape_markup helper for Textual rendering
    stx.tcss# global stylesheet
    screens/
      __init__.py      # re-exports all modals
      base_edit.py     # BaseEditModal, ModalScroll — shared form scaffolding
      metadata.py      # MetadataModal — generic key/value editor for all 4 entity kinds
      task_edit.py     # TaskEditModal
      task_create.py   # TaskCreateModal
      project_edit.py  # ProjectEditModal
      project_create.py# ProjectCreateModal
      group_edit.py    # GroupEditModal
      group_create.py  # GroupCreateModal
      status_create.py # StatusCreateModal — name + workspace selector (defaults to active)
      workspace_create.py  # WorkspaceCreateModal — name only
      workspace_edit.py    # WorkspaceEditModal
      workspace_switch.py  # WorkspaceSwitchModal
      new_resource.py  # NewResourceModal — resource type selector (task/group/project/status/workspace)
      config_modal.py  # ConfigModal — in-TUI settings editor (theme, auto_refresh_seconds), bound to `c`
    widgets/
      __init__.py        # re-exports widgets
      workspace_tree.py  # WorkspaceTree — left-panel tree widget
      kanban_board.py    # KanbanBoard + KanbanColumn — right-panel kanban with diff-based sync, focusable columns with shift+left/right reorder
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
  test_metadata_modal.py     # MetadataModal tests (all 4 entity kinds)
  test_markdown_editor.py    # markdown editor widget tests
```

## CLI

Entry point: `stx = "stx.__main__:main"`.

**Active workspace:** persisted as `active_workspace` in `~/.config/stx/tui.toml`. CLI resolves workspace from `--workspace`/`-w` flag, falling back to this config field. Set via `stx workspace use <name>` or `stx config set active_workspace <name>`. The legacy `~/.local/share/stx/active-workspace` file is still read as a fallback for one release; writes no longer go there.

**Command structure:**
- Task subcommands: `stx task create|ls|show|edit|mv|transfer|archive|log` (`create` accepts `--group/-g`)
- Task metadata: `stx task meta ls|get|set|del` (JSON key/value blob on each task)
- Workspace metadata: `stx workspace meta ls|get|set|del` (operates on active workspace or `-w` override)
- Project metadata: `stx project meta ls|get|set|del <project>`
- Group metadata: `stx group meta ls|get|set|del <title> [--project]`
- Project subcommands: `stx project create|ls|show|edit|rename|archive`
- Group subcommands: `stx group create|ls|show|rename|edit|archive|mv|assign|unassign|dep`
- Workspace subcommands: `stx workspace create|ls|show|use|rename|archive`
- Other subcommand groups: `workspace`, `status`, `dep`, `tag`
- Config subcommands: `stx config ls|get|set|unset` — edit `auto_refresh_seconds` and `active_workspace` in `tui.toml`. `ls`/`get` can read any field; `set`/`unset` are gated by an editable-field allowlist.
- Standalone commands: `export`, `info`, `backup`

## TUI

Entry point: `stx tui` (or `stx tui --db path/to/db`).

**Architecture:**
- **Model** (`tui/model.py`): `WorkspaceModel` loads all non-archived data for the active workspace via existing service functions, then organizes it into a tree: `WorkspaceModel` → `ProjectNode` → `GroupNode` (recursive). Tasks without a project live in `unassigned_tasks`. Groups nest recursively via `parent_id`. Dependency-aware topological ordering for both tree and kanban.
- **View / Controller** (`tui/app.py`): `StxApp` — two-panel layout. Left: `#workspaces-panel` (25% width) with `WorkspaceTree`. Right: `#kanban-panel` with `KanbanBoard` — one scrollable column per status with `TaskCard` widgets. Diff-based kanban sync with coalescing refresh (duplicates merge in the message queue). `app.py` acts as both view and controller — dispatches keybindings, pushes modals, calls service layer on dismiss.
- **Screens**: `BaseEditModal` provides shared form scaffolding: save/cancel buttons, error display, field navigation (`ctrl+n`/`ctrl+b`), date parsing (`_parse_date_field`), change diffing (`_diff_and_dismiss`). Edit modals diff form values against the original entity and dismiss with changes only. Create modals dismiss with the full form data dict. `_dismiss_callback` in `app.py` wraps the common null-check → try/except → notify → refresh pattern for all modal callbacks.
- **Widgets**: `WorkspaceTree` (tree with emoji prefixes: workspace, project, group, task — node `data` carries the model object), `KanbanBoard` (diff-based card sync, status-move via `[`/`]` or `shift+left/right`), `KanbanColumn` (focusable; `shift+left/right` while focused reorders the column and persists to `tui.toml`), `TaskCard` (focusable, renders task summary), `MarkdownEditor` (edit/preview toggle for description fields).

**Keybindings:**
| Key | Action |
|-----|--------|
| `w` | Focus workspace tree |
| `b` | Focus kanban board |
| `r` | Refresh |
| `e` | Edit selected entity |
| `m` | Edit metadata on selected entity (task/workspace/project/group) |
| `c` | Open settings modal (theme, auto_refresh_seconds) |
| `n` | Create new (task/group/project/status/workspace selector) |
| `s` | Switch workspace |
| `[` / `]` / `shift+left` / `shift+right` | Task card focused → move task across statuses. Status column focused → reorder the column (persisted to `tui.toml`). |
| `ctrl+q` | Quit |

**Config:** `~/.config/stx/tui.toml` — theme, show_archived, confirm_archive, default_priority, status_order, auto_refresh_seconds, active_workspace. Loaded via `TuiConfig` dataclass in `tui/config.py`. Status order is editable from the CLI via `stx status order <status_1> <status_2> ...` (scoped to the active workspace / `-w` override) or interactively via `shift+left/right` on a focused kanban column. Theme and `auto_refresh_seconds` are also editable in-TUI via the settings modal (`c` key, `tui/screens/config_modal.py`).

## Key Design Conventions

- **Separate pre-insert and persisted types** — `NewTask` (no `id`/`created_at`) vs `Task` (full row). Never use `None` as a stand-in for "not yet assigned."
- **ListItem vs Detail service models** — two tiers of denormalization for tasks. `TaskListItem` is a flat dataclass of Task fields plus resolved display names (`project_name`, `tag_names`) for list rendering without per-row lookups. `TaskDetail` is a flat dataclass of Task fields plus fully hydrated relationships (`status`, `project`, `group`, `blocked_by`, `blocks`, `history`, `tags`) for single-entity views. Both redeclare Task fields directly — they do not inherit from `Task`. `GroupRef` is the only surviving Ref type, used by `list_groups` to page through the hierarchy without hydrating every group. `WorkspaceListView` is the aggregate view model for `cmd_ls` — workspace + ordered statuses + TaskListItems. `WorkspaceContext` is the aggregate view model for `cmd_workspace_show` — `WorkspaceListView` + projects + tags + groups, for one-call AI session startup.
- **All dataclasses are frozen** — immutability throughout. Changes produce new instances via DB.
- **Defaults on pre-insert dataclasses** — optional/defaultable fields on `New*` types carry defaults directly. No factory layer needed.
- **Service models are flat, not inherited** — `TaskListItem`, `TaskDetail`, `ProjectDetail`, and `GroupDetail` redeclare their parent entity's fields rather than inheriting from `Task` / `Project` / `Group`. Tradeoff: adding a column to `tasks` touches both `TaskListItem` and `TaskDetail` in addition to `Task` and `row_to_task`. The win is that hydrated fields can be plain required annotations (e.g. `status: Status` on `TaskDetail`) without dataclass field-ordering gymnastics. An earlier inheritance-based version required `status: Status = None  # type: ignore` with a runtime `__post_init__` check — flat redeclaration removes that hack.
- **Mappers are plain functions** — explicit conversion at each layer boundary (row→model, model→ref, ref→detail). Models are pure data containers with no methods — conversion logic stays in `mappers.py`, not as classmethods. Accept the boilerplate to keep separation clean.
- **`shallow_fields()` helper** — extracts a dataclass's fields as a dict for splatting into derived types (`TaskListItem`, `TaskDetail`, `GroupRef`, etc.). Lives in `mappers.py`.
- **Repository update allowlists** — each entity has a `_*_UPDATABLE` frozenset guarding which fields can be passed to update functions.
- **Journal / audit trail** — `_record_entity_changes()` in the service layer records `JournalEntry` rows for any entity mutation. `_record_dependency_change()` handles dependency link/unlink. Metadata mutations emit `meta.<key>` field entries via `_set_entity_meta` / `_remove_entity_meta` / `_replace_entity_metadata`. `EntityType` StrEnum defines the seven entity types (`task`, `project`, `group`, `workspace`, `status`, `task_dependency`, `group_dependency`). Per-entity field enums (`TaskField`, `ProjectField`, `GroupField`, `WorkspaceField`, `StatusField`, `DependencyField`) exist for documentation and validation but `journal.field` is an unconstrained TEXT column.
- **Transaction context manager** — service layer controls transaction boundaries. Repository functions receive a connection and never commit/rollback. On rollback failure, `raise exc from rollback_exc` — the original error is primary, rollback failure is attached as `__cause__`. This is intentional.
- **Timestamps as Unix epoch integers** — formatting happens at the edges only. `parse_date` and `format_timestamp` live in `formatting.py` (shared by CLI and TUI).
- **Task numbers** — formatted as `task-{id:04d}` in the application layer, derived from autoincrement ID. `format_task_num` and `format_priority` also live in `formatting.py`.
- **Active workspace** — persisted as the `active_workspace` field in `~/.config/stx/tui.toml`. CLI resolves workspace from `--workspace` flag or this config field. Legacy `~/.local/share/stx/active-workspace` file is still read as a one-release fallback; writes go to `tui.toml`.
- **Tags** — workspace-scoped, many-to-many with tasks via `task_tags` junction table. `tag_task` auto-creates the tag if it doesn't exist. Composite FKs enforce same-workspace scoping at the DB level.
- **Error translation** — `_friendly_errors()` context manager in the service layer catches `IntegrityError` and translates to `ValueError` with human-readable messages. `_UNIQUE_MESSAGES` dict maps constraint patterns to messages.
- **Service-layer pre-validation** — `_validate_task_fields()` checks scalar constraints (priority range, position >= 0, date ordering) and cross-entity constraints (status/project exists, on correct workspace, not archived) before hitting the DB. `_validate_group_project_consistency()` separately enforces the (project_id, group_id) invariant whenever either field is in an update's `changes` dict — catches both "assign a group to a task in the wrong project" and "change project out from under an existing group". `update_task` is split into an outer public entry point that owns the transaction and an inner `_update_task_body` that can be called from service functions already holding a transaction (e.g. the `assign_task_to_group` wrapper).
- **Entity metadata** — tasks, workspaces, projects, and groups each carry a JSON key/value blob (`metadata TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata))`). Keys are normalized to lowercase on write/read via `_normalize_meta_key()` in service (matching the codebase's `COLLATE NOCASE` convention, which doesn't apply to JSON fields directly). Key charset: `[a-z0-9_.-]+`, max 64 chars. Values are free-form text up to 500 chars. Generic helpers `_set_entity_meta` / `_get_entity_meta` / `_remove_entity_meta` / `_replace_entity_metadata` take `setter`/`writer`/`fetcher`/`remover` callables so the per-entity public functions (`set_task_meta`, `replace_workspace_metadata`, etc.) are one-line delegates. Repository mirrors this with generic `_set_metadata_key` / `_remove_metadata_key` / `_replace_metadata` helpers guarded by a `_METADATA_TABLES` allowlist. The per-key `set/remove/get_*_meta` functions and the bulk `replace_*_metadata` functions are two sides of the same surface: CLI uses per-key writes (`stx {task,workspace,project,group} meta set/del`), while the TUI `MetadataModal` uses bulk-replace (`replace_*_metadata`) for atomic multi-key edits. All metadata mutations now emit journal entries (`meta.<key>` field encoding). The `source` parameter is propagated through all delegates and recorded in the journal.
- **Migrations** — numbered SQL files in `src/stx/migrations/` (e.g., `004_column_to_status.sql`). `_run_migrations()` discovers files by version prefix, wraps each in FK-off + transaction + FK-revalidate. SQL files contain only DDL/DML — no PRAGMAs, no transaction control. `SCHEMA_VERSION` is explicit; a test asserts it matches the highest migration file number. Fresh databases skip migrations entirely (`init_db` runs `schema.sql` and stamps `SCHEMA_VERSION`). When recreating tables with FK deps (e.g. `tasks`), cascade-recreate dependent tables (`task_dependencies`, `task_tags`, `journal`); use `CASE` in INSERT to transform field values rather than UPDATE before recreate (avoids violating the old CHECK constraint).- **BaseEditModal pattern** — shared TUI modal base class providing save/cancel buttons, error display, `ctrl+n`/`ctrl+b` field navigation, `_do_save` (subclass hook), `_diff_and_dismiss` (edit modals), and `_parse_date_field` (date input validation). `_dismiss_callback` on `StxApp` wraps the null-check → try/except ValueError → notify → refresh pattern used by all modal callbacks.
- **MetadataModal** — single generic `MetadataModal(display_title, metadata, result_key, entity_id)` in `tui/screens/metadata.py` serves all four entity kinds (tasks, workspaces, projects, groups). Reached via the `m` keybinding in `app.py::action_metadata`, which dispatches on the focused tree node's `.data` type (or the focused kanban card for tasks) to one of four `_open_*_metadata` builders. Each builder constructs the `display_title` + passes the entity's current metadata dict + a `result_key` (`task_id` / `workspace_id` / `project_id` / `group_id`). On save the modal dismisses with `{result_key: id, "metadata": new_dict}` and the corresponding `_on_*_metadata_dismiss` handler routes to `service.replace_*_metadata`. The modal's save-diff compares normalized (lowercase-keyed) forms so retyping a key's case alone is a no-op, matching the service-side normalization.
- **Export** — `export.py` renders the full database to Markdown with Mermaid dependency graphs.
- **DB path** — `~/.local/share/stx/stx.db` (XDG-compliant).
- **WAL journal mode** — enables concurrent reads from TUI and CLI.
- **Releases** — version lives in two files that must move together: `pyproject.toml` (Python package) and `.claude-plugin/plugin.json` (Claude Code plugin). See `RELEASING.md` for the full checklist (pre-release tests, version bump, `CHANGELOG.md` promotion, tag, push). User-visible changes go into `CHANGELOG.md` under `## [Unreleased]` as they land, then get promoted to a versioned section at release time.

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
