# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A local todo/kanban app (`todo` CLI) with two interfaces: CLI (argparse) and TUI (Textual), backed by SQLite storage. All layers are fully implemented. Use `--json` flag for structured CLI output. Use the `/todo` command for full CLI reference.

## Architecture

```
CLI commands ────────┐
TUI event handlers ──┤──▶ Service ──▶ Repository ──▶ Connection ──▶ SQLite
```

**Data hierarchy:** Board → Column → Task (and Board → Project → Task, Board → Tag ↔ Task). Columns are board-scoped and represent kanban workflow stages. No data is ever deleted — use `archived` flags instead.

## Project Structure

```
src/sticky_notes/
  __main__.py        # entry point (todo command)
  cli.py             # argparse CLI — commands, output formatting
  formatting.py      # shared formatting: format_task_num, format_priority, parse_date, format_timestamp
  service.py         # business logic, transaction boundaries
  repository.py      # raw SQL queries, one function per operation
  connection.py      # SQLite connection factory, schema init, migration runner
  models.py          # domain dataclasses (New*, persisted)
  service_models.py  # Ref/Detail dataclasses for service layer
  mappers.py         # row→model, model→ref, ref→detail converters
  export.py          # full-database Markdown + Mermaid export
  schema.sql         # DDL (current schema, used for fresh databases)
  migrations/        # numbered SQL migration files (001_*.sql, 002_*.sql, ...)
  tui/
    app.py           # StickyNotesApp — main Textual app shell
    config.py        # TuiConfig dataclass, TOML load/save
    markup.py        # escape_markup helper for Textual rendering
    sticky_notes.tcss# global stylesheet
    screens/
      settings.py    # SettingsScreen — theme, board, display preferences
      confirm_dialog.py # ConfirmDialog(ModalScreen[bool]) — reusable yes/no
      task_detail.py # TaskDetailModal(ModalScreen[int|None]) — read-only detail
      task_form.py   # TaskFormModal(ModalScreen[dict|None]) — create/edit form
    widgets/
      board_view.py  # BoardView — kanban grid with navigation, CRUD handlers
      column_widget.py # ColumnWidget — single column with header and task cards
      task_card.py   # TaskCard — focusable card with keybindings and messages

tests/
  conftest.py        # fixtures (fresh DB, seeded board/columns/tasks)
  helpers.py         # raw SQL insert helpers for test setup
  seed.py            # seed_board() for TUI test fixtures and manual testing
  test_cli.py        # CLI integration tests
  test_connection.py
  test_export.py
  test_mappers.py
  test_repository.py
  test_service.py
  test_tui.py        # TUI tests: config, app, settings, board, nav, move, archive, detail, create, edit
```

## CLI

Entry point: `todo = "sticky_notes.__main__:main"`.

**Active board:** persisted at `~/.local/share/sticky-notes/active-board`. CLI resolves board from `--board`/`-b` flag, falling back to this file. Set via `todo board create` or `todo board use`.

**Command structure:**
- Top-level task commands: `add`, `ls`, `show`, `edit`, `mv`, `done`, `rm`, `log`
- Subcommand groups: `board`, `col`, `project`, `dep`, `tag`, `export`

## TUI

Entry point: `todo --tui` (or `todo --tui --db path/to/db`).

**Architecture:** `StickyNotesApp` → `BoardView` (main widget) → `ColumnWidget` → `TaskCard`. Screens are `ModalScreen[T]` overlays that dismiss with typed results via callbacks.

**Keybindings (on TaskCard focus):**
- `enter` — task detail modal (read-only)
- `e` — edit task (form pre-populated)
- `d` / `delete` — archive task (with optional confirmation)
- `n` — new task in focused column
- Arrow keys — navigate grid; `shift+left`/`shift+right` — move task between columns

**Screen patterns:**
- `ConfirmDialog(ModalScreen[bool])` — generic yes/no, reusable for any destructive action
- `TaskDetailModal(ModalScreen[int | None])` — dismisses with `None` (close) or task_id (edit transition)
- `TaskFormModal(ModalScreen[dict | None])` — dual-mode (`Literal["create", "edit"]`), dismisses with field dict or `None` (cancel)

**Key conventions:**
- Deferred screen imports in `board_view.py` handler methods to avoid circular deps between widgets and screens
- `BoardView.reload(focus_task_id=None)` is the single re-render path — all mutations call it
- `BoardView._board_id` cached during `_load_board()` — handlers use it instead of fishing from column slots
- `TaskFormModal` takes `conn` + `board_id` in constructor (pre-mount data fetching), `default_priority` as explicit param — no `typed_app` access before mount
- Edit diffs form result against current DB state for minimal `update_task` changes dict
- Config at `~/.config/sticky-notes/tui.toml` — theme, show_archived, confirm_archive, default_priority

## Key Design Conventions

- **Separate pre-insert and persisted types** — `NewTask` (no `id`/`created_at`) vs `Task` (full row). Never use `None` as a stand-in for "not yet assigned."
- **Ref vs Detail service models** — `TaskRef` carries relationship IDs (cheap, for lists). `TaskDetail` carries hydrated objects (expensive, for detail views).
- **All dataclasses are frozen** — immutability throughout. Changes produce new instances via DB.
- **Defaults on pre-insert dataclasses** — optional/defaultable fields on `New*` types carry defaults directly. No factory layer needed.
- **Service models inherit from domain models** — `TaskRef(Task)`, `TaskDetail(TaskRef)`, etc. Inheritance chain: `Task → TaskRef → TaskDetail`. Child fields use defaults to satisfy dataclass field ordering. Access task fields directly (`ref.title`), not via composition.
- **Mappers are plain functions** — explicit conversion at each layer boundary (row→model, model→ref, ref→detail). Models are pure data containers with no methods — conversion logic stays in `mappers.py`, not as classmethods. Accept the boilerplate to keep separation clean.
- **`shallow_fields()` helper** — extracts parent dataclass fields as a dict for constructing derived types (Ref, Detail). Lives in `mappers.py`.
- **Repository update allowlists** — each entity has a `_*_UPDATABLE` frozenset guarding which fields can be passed to update functions.
- **Task history / audit trail** — `_record_changes()` in the service layer auto-records `TaskHistory` entries for changed fields. `TaskField` enum defines trackable fields.
- **Transaction context manager** — service layer controls transaction boundaries. Repository functions receive a connection and never commit/rollback. On rollback failure, `raise exc from rollback_exc` — the original error is primary, rollback failure is attached as `__cause__`. This is intentional.
- **Timestamps as Unix epoch integers** — formatting happens at the edges only. `parse_date` and `format_timestamp` live in `formatting.py` (shared by CLI and TUI).
- **Task numbers** — formatted as `task-{id:04d}` in the application layer, derived from autoincrement ID. `format_task_num` and `format_priority` also live in `formatting.py`.
- **Active board file** — persisted at `~/.local/share/sticky-notes/active-board`. CLI resolves board from `--board` flag or this file.
- **Tags** — board-scoped, many-to-many with tasks via `task_tags` junction table. `tag_task` auto-creates the tag if it doesn't exist. Composite FKs enforce same-board scoping at the DB level.
- **Error translation** — `_friendly_errors()` context manager in the service layer catches `IntegrityError` and translates to `ValueError` with human-readable messages. `_UNIQUE_MESSAGES` dict maps constraint patterns to messages.
- **Service-layer pre-validation** — `_validate_task_fields()` checks scalar constraints (priority range, position >= 0, date ordering) and cross-entity constraints (column/project exists, on correct board, not archived) before hitting the DB.
- **Migrations** — numbered SQL files in `src/sticky_notes/migrations/` (e.g., `003_schema_hardening.sql`). `_run_migrations()` discovers files by version prefix, wraps each in FK-off + transaction + FK-revalidate. SQL files contain only DDL/DML — no PRAGMAs, no transaction control. `SCHEMA_VERSION` is explicit; a test asserts it matches the highest migration file number. Fresh databases skip migrations entirely (`init_db` runs `schema.sql` and stamps `SCHEMA_VERSION`).
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
