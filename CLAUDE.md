# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A structured context and task management app (`stx` CLI) with two interfaces: CLI (argparse) and TUI (Textual), backed by SQLite storage. All layers are fully implemented. CLI auto-emits JSON when piped and text at a terminal (`--json`/`--text` override). See `skills/stx/references/cli-reference.md` for the full CLI reference and `skills/stx/references/json-schema.md` for JSON shapes.

## Architecture

```
CLI commands ────────┐
TUI event handlers ──┤──▶ Service ──▶ Repository ──▶ Connection ──▶ SQLite
```

**Data hierarchy:** Workspace → Group (recursive) → Task (and Workspace → Status → Task). Groups nest via `parent_id`; root groups have `parent_id IS NULL`. Statuses are workspace-scoped and represent kanban workflow stages. No data is ever deleted — use `archived` flags instead.

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
      group_edit.py    # GroupEditModal
      group_create.py  # GroupCreateModal
      status_create.py # StatusCreateModal — name + workspace selector (defaults to active)
      workspace_create.py  # WorkspaceCreateModal — name only
      workspace_edit.py    # WorkspaceEditModal
      workspace_switch.py  # WorkspaceSwitchModal
      new_resource.py  # NewResourceModal — resource type selector (task/group/status/workspace)
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
  test_edit_modals.py        # group, workspace edit modal tests
  test_create_modals.py      # create modal + resource selector tests
  test_metadata_modal.py     # MetadataModal tests (all 3 entity kinds)
  test_markdown_editor.py    # markdown editor widget tests
```

## CLI

Entry point: `stx = "stx.__main__:main"`.

**Active workspace:** persisted as `active_workspace` in `~/.config/stx/tui.toml`. CLI resolves workspace from `--workspace`/`-w` flag, falling back to this config field. Set via `stx workspace use <name>` or `stx config set active_workspace <name>`. The legacy `~/.local/share/stx/active-workspace` file is still read as a fallback for one release; writes no longer go there.

**Path-based ref syntax (groups + tasks):** `/` separates group-path segments anchored at root; `:` separates the group prefix from a task title; a leading `/` is a no-op anchor that promotes single-segment refs to group paths (Unix-style absolute path).
- `setup` — bare title; workspace-wide lookup, ambiguity errors. In polymorphic edge contexts, bare resolves as a task.
- `/A` — root group `A` (leading-slash anchor disambiguates single-segment refs from bare task titles in polymorphic contexts).
- `A/B/C` (or `/A/B/C`) — group-path walk: root `A` → `B` → `C`. Leading slash is cosmetic for multi-segment.
- `A/B:leaf` (or `/A/B:leaf`) — task `leaf` inside group `A/B`.
- `:rootleaf` — task `rootleaf` with no group.
- `task:`/`group:`/`workspace:`/`status:` edge prefixes consume the leading token; the suffix uses the same path syntax. Generally unnecessary now that the leading-slash anchor disambiguates root groups; kept for explicitness.
- `/` and `:` are forbidden in group/task titles (enforced by `service._validate_title` and a `CHECK` constraint in `schema.sql`). Migration 022 auto-renames pre-existing offenders to `__` equivalents with deterministic collision suffixing.
- Resolvers: `service.parse_ref` (pure, no DB) → `service.resolve_group_path` / `service.resolve_task_path`. `service.resolve_group(ref)` and `service.resolve_task_id(ref)` dispatch through `parse_ref`. Group-only path passed to `resolve_task_id` (or vice versa) raises `ValueError`.

**Command structure:**
- Task subcommands: `stx task create|ls|show|edit|mv|transfer|archive|log|done|undone` (`create` accepts `--group/-g`; `done` marks done independent of status; `undone` clears done, gated by `--force`)
- Task metadata: `stx task meta ls|get|set|del` (JSON key/value blob on each task)
- Workspace metadata: `stx workspace meta ls|get|set|del` (operates on active workspace or `-w` override)
- Group metadata: `stx group meta ls|get|set|del <title>`
- Group subcommands: `stx group create|ls|show|edit|archive|mv|assign|unassign` (rename via `edit --title`)
- Workspace subcommands: `stx workspace create|ls|show|use|edit|archive` (rename via `edit --name`)
- Edge subcommands: `stx edge create|archive|ls` and `stx edge meta ls|get|set|del` — polymorphic. Endpoint type is inferred from path delimiters when no explicit prefix is given: `task-NNNN`/`#N`/int → task by id; leading `/` (`/A`, `/A/B/C`) → group path; `A/B/C` (only `/`, multi-segment) → group path; `A:leaf`/`:leaf`/`A/B:leaf` (contains `:`) → task path; bare title (no delimiters) → task by title. Explicit prefixes `group:<path>`/`task:<path>`/`workspace:<name>`/`status:<name>` always override inference. Cross-type edges work (group→task, task→group, etc.) — `--source /A/B --target D:task0` is a clean group→task edge. Each edge carries a `--kind` label, a per-edge metadata blob, and an `acyclic` flag (defaults: on for `blocks`/`spawns`, off for everything else). Status edges are pure annotation — they carry no write-path semantics. The legacy `--source-parent`/`--target-parent` flags were removed in 0.15. Self-loops are rejected by DB CHECK. Cycle detection runs on the combined acyclic-edge subgraph regardless of kind.
- Other subcommand groups: `workspace`, `status`
- Config subcommands: `stx config ls|get|set|unset` — edit `auto_refresh_seconds` and `active_workspace` in `tui.toml`. `ls`/`get` can read any field; `set`/`unset` are gated by an editable-field allowlist.
- Standalone commands: `export`, `info`, `backup`, `next` (topological sort of acyclic DAG to surface ready/blocked tasks; flags: `--rank`, `--include-blocked`, `--limit N`, `--edge-kind KIND`)
- Status edit: `stx status edit <name> [--name NEW] [--terminal|--no-terminal]` — `--terminal`/`--no-terminal` marks/unmarks a status as terminal; tasks moved into a terminal status auto-set `done=True`

## TUI

Entry point: `stx tui` (or `stx tui --db path/to/db`).

**Architecture:**
- **Model** (`tui/model.py`): `WorkspaceModel` loads all non-archived data for the active workspace via existing service functions, then organizes it into a tree: `WorkspaceModel` → root groups → `GroupNode` (recursive). Tasks without a group (`group_id IS NULL`) live in `unassigned_tasks`. Groups nest recursively via `parent_id`.
- **View / Controller** (`tui/app.py`): `StxApp` — two-panel layout. Left: `#workspaces-panel` (25% width) with `WorkspaceTree`. Right: `#kanban-panel` with `KanbanBoard` — one scrollable column per status with `TaskCard` widgets. Diff-based kanban sync with coalescing refresh (duplicates merge in the message queue). `app.py` acts as both view and controller — dispatches keybindings, pushes modals, calls service layer on dismiss.
- **Screens**: `BaseEditModal` provides shared form scaffolding: save/cancel buttons, error display, field navigation (`ctrl+n`/`ctrl+b`), date parsing (`_parse_date_field`), change diffing (`_diff_and_dismiss`). Edit modals diff form values against the original entity and dismiss with changes only. Create modals dismiss with the full form data dict. `_dismiss_callback` in `app.py` wraps the common null-check → try/except → notify → refresh pattern for all modal callbacks.
- **Widgets**: `WorkspaceTree` (tree with emoji prefixes: workspace, group, task — node `data` carries the model object), `KanbanBoard` (diff-based card sync, status-move via `[`/`]` or `shift+left/right`), `KanbanColumn` (focusable; `shift+left/right` while focused reorders the column and persists to `tui.toml`), `TaskCard` (focusable, renders task summary), `MarkdownEditor` (edit/preview toggle for description fields).

**Keybindings:**
| Key | Action |
|-----|--------|
| `w` | Focus workspace tree |
| `b` | Focus kanban board |
| `r` | Refresh |
| `e` | Edit selected entity |
| `m` | Edit metadata on selected entity (task/workspace/group) |
| `c` | Open settings modal (theme, auto_refresh_seconds) |
| `n` | Create new (task/group/status/workspace selector) |
| `s` | Switch workspace |
| `[` / `]` / `shift+left` / `shift+right` | Task card focused → move task across statuses. Status column focused → reorder the column (persisted to `tui.toml`). |
| `ctrl+q` | Quit |

**Config:** `~/.config/stx/tui.toml` — theme, show_archived, confirm_archive, default_priority, status_order, auto_refresh_seconds, active_workspace. Loaded via `TuiConfig` dataclass in `tui/config.py`. Status order is editable from the CLI via `stx status order <status_1> <status_2> ...` (scoped to the active workspace / `-w` override) or interactively via `shift+left/right` on a focused kanban column. Theme and `auto_refresh_seconds` are also editable in-TUI via the settings modal (`c` key, `tui/screens/config_modal.py`).

## Key Design Conventions

- **Separate pre-insert and persisted types** — `NewTask` (no `id`/`created_at`) vs `Task` (full row). Never use `None` as a stand-in for "not yet assigned."
- **ListItem vs Detail service models** — two tiers of denormalization for tasks. `TaskListItem` is a flat dataclass of Task fields for list rendering without per-row lookups. `TaskDetail` is a flat dataclass of Task fields plus fully hydrated relationships (`status`, `group`, `edge_sources`, `edge_targets`, `history`) for single-entity views. Both redeclare Task fields directly — they do not inherit from `Task`. `GroupRef` is the only surviving Ref type, used by `list_groups` to page through the hierarchy without hydrating every group. `WorkspaceListView` is the aggregate view model for `cmd_ls` — workspace + ordered statuses + TaskListItems. `WorkspaceContext` is the aggregate view model for `cmd_workspace_show` — `WorkspaceListView` + groups, for one-call AI session startup.
- **All dataclasses are frozen** — immutability throughout. Changes produce new instances via DB.
- **Defaults on pre-insert dataclasses** — optional/defaultable fields on `New*` types carry defaults directly. No factory layer needed.
- **Service models are flat, not inherited** — `TaskListItem`, `TaskDetail`, and `GroupDetail` redeclare their parent entity's fields rather than inheriting from `Task` / `Group`. Tradeoff: adding a column to `tasks` touches both `TaskListItem` and `TaskDetail` in addition to `Task` and `row_to_task`. The win is that hydrated fields can be plain required annotations (e.g. `status: Status` on `TaskDetail`) without dataclass field-ordering gymnastics. An earlier inheritance-based version required `status: Status = None  # type: ignore` with a runtime `__post_init__` check — flat redeclaration removes that hack.
- **Mappers are plain functions** — explicit conversion at each layer boundary (row→model, model→ref, ref→detail). Models are pure data containers with no methods — conversion logic stays in `mappers.py`, not as classmethods. Accept the boilerplate to keep separation clean.
- **`shallow_fields()` helper** — extracts a dataclass's fields as a dict for splatting into derived types (`TaskListItem`, `TaskDetail`, `GroupRef`, etc.). Lives in `mappers.py`.
- **Repository update allowlists** — each entity has a `_*_UPDATABLE` frozenset guarding which fields can be passed to update functions.
- **Journal / audit trail** — `_record_entity_changes()` in the service layer records `JournalEntry` rows for any entity mutation. `_record_edge_change()` handles edge link/unlink for the polymorphic `edges` table. Metadata mutations emit `meta.<key>` field entries via `_set_entity_meta` / `_remove_entity_meta` / `_replace_entity_metadata`. `EntityType` StrEnum defines five entity types (`task`, `group`, `workspace`, `status`, `edge`). Per-entity field enums (`TaskField`, `GroupField`, `WorkspaceField`, `StatusField`, `EdgeField`) exist for documentation and validation but `journal.field` is an unconstrained TEXT column. Edge endpoints are journaled as `"<from_type>:<from_id>→<to_type>:<to_id>"` on the `endpoint` field.
- **Transaction context manager** — service layer controls transaction boundaries. Repository functions receive a connection and never commit/rollback. On rollback failure, `raise exc from rollback_exc` — the original error is primary, rollback failure is attached as `__cause__`. This is intentional.
- **Timestamps as Unix epoch integers** — formatting happens at the edges only. `parse_date` and `format_timestamp` live in `formatting.py` (shared by CLI and TUI).
- **Task numbers** — formatted as `task-{id:04d}` in the application layer, derived from autoincrement ID. `format_task_num` and `format_priority` also live in `formatting.py`.
- **Active workspace** — persisted as the `active_workspace` field in `~/.config/stx/tui.toml`. CLI resolves workspace from `--workspace` flag or this config field. Legacy `~/.local/share/stx/active-workspace` file is still read as a one-release fallback; writes go to `tui.toml`.
- **Error translation** — `_friendly_errors()` context manager in the service layer catches `IntegrityError` and translates to `ValueError` with human-readable messages. `_UNIQUE_MESSAGES` dict maps constraint patterns to messages.
- **Service-layer pre-validation** — `_validate_task_fields()` checks scalar constraints (priority is int, date ordering) and cross-entity constraints (status exists, on correct workspace, not archived) before hitting the DB. `update_task` is split into an outer public entry point that owns the transaction and an inner `_update_task_body` that can be called from service functions already holding a transaction (e.g. the `assign_task_to_group` wrapper).
- **Entity metadata** — tasks, workspaces, and groups each carry a JSON key/value blob (`metadata TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata))`). **Statuses do not carry metadata.** Keys are normalized to lowercase on write/read via `_normalize_meta_key()` in service (matching the codebase's `COLLATE NOCASE` convention, which doesn't apply to JSON fields directly). Key charset: `[a-z0-9_.-]+`, max 64 chars. Values are free-form text up to 500 chars. Generic helpers `_set_entity_meta` / `_get_entity_meta` / `_remove_entity_meta` / `_replace_entity_metadata` take `setter`/`writer`/`fetcher`/`remover` callables so the per-entity public functions (`set_task_meta`, `replace_workspace_metadata`, etc.) are one-line delegates. Repository mirrors this with generic `_set_metadata_key` / `_remove_metadata_key` / `_replace_metadata` helpers guarded by a `_METADATA_TABLES` allowlist. The per-key `set/remove/get_*_meta` functions and the bulk `replace_*_metadata` functions are two sides of the same surface: CLI uses per-key writes (`stx {task,workspace,group} meta set/del`), while the TUI `MetadataModal` uses bulk-replace (`replace_*_metadata`) for atomic multi-key edits. All metadata mutations emit journal entries (`meta.<key>` field encoding). The `source` parameter is propagated through all delegates and recorded in the journal. Edges have their own metadata blob, accessed via `stx edge meta ls|get|set|del`; the unified `edges` table lives outside the `_METADATA_TABLES` single-id allowlist and uses its own composite-key helpers.
- **`done` flag and `is_terminal`** — `task.done` is a sticky boolean set when a task enters a terminal status or via `mark_task_done`; cleared only by `mark_task_undone`. `status.is_terminal` controls the auto-flip (entry only — leaving a terminal status does not clear done). `group.done` is a read-only rollup: `_propagate_done_upward` walks the parent chain post-commit, recomputing each group's done state via `repo.compute_group_done_state` (true iff every non-archived child task and subgroup is done and the group is non-empty). `compute_next_tasks` consults `task.done` only — never `group.done`. Service models: `NextTasksView(workspace_id, ready: tuple[TaskListItem], blocked: tuple[BlockedTask])` and `BlockedTask(task: TaskListItem, blocked_by: tuple[int, ...])` — `blocked_by` is always non-empty (enforced by `__post_init__`).
- **Optimistic locking** — every mutable entity table carries a `version INTEGER NOT NULL DEFAULT 0` column, incremented unconditionally on every write by `_build_update` in `repository.py`. Callers pass `expected_version` to get `WHERE id=? AND version=?` semantics; zero rowcount raises `ConflictError` (subclass of `ValueError`). `_raise_on_zero_rowcount` distinguishes version conflict from not-found by checking row existence after the failed update. The CLI `_with_cas_retry(fetch, already, action)` helper re-fetches and retries up to `_MAX_CAS_RETRIES=3` times; on exhaustion the `ConflictError` propagates to `main()` → exit code 6 (`EXIT_CONFLICT`).
- **Post-commit rollup propagation** — `_propagate_done_upward` must run in a separate transaction from the entity write that triggered it, so its reads see the fully committed state from concurrent agents (SQLite snapshot isolation would hide concurrent writes within the same transaction). All write paths that affect group rollup (`update_task`, `update_group`, `archive_task`, `cascade_archive_group`, `assign_task_to_group`) collect affected parent IDs into a `parents: set[int]` during the write transaction, then iterate post-commit — each parent in its own `with transaction(conn)`.
- **Migrations** — numbered SQL files in `src/stx/migrations/` (e.g., `004_column_to_status.sql`), currently through `021_version_columns.sql` (`SCHEMA_VERSION = 21` in `connection.py`). `_run_migrations()` discovers files by version prefix, wraps each in FK-off + transaction + FK-revalidate. SQL files contain only DDL/DML — no PRAGMAs, no transaction control. A test asserts `SCHEMA_VERSION` matches the highest migration file number. Fresh databases skip migrations entirely (`init_db` runs `schema.sql` and stamps `SCHEMA_VERSION`). When recreating tables with FK deps (e.g. `tasks`), cascade-recreate dependent tables (`edges`, `journal`); use `CASE` in INSERT to transform field values rather than UPDATE before recreate (avoids violating the old CHECK constraint). Migration 015 removed projects (old projects folded into root groups). Migration 016 unified `task_edges` + `group_edges` into a single polymorphic `edges` table keyed on `(from_type, from_id, to_type, to_id, kind)`, rewrote `journal.entity_type` rows for `task_edge`/`group_edge` to `edge`, and added the per-edge `acyclic` flag. Migration 020 added `done` to tasks/groups and `is_terminal` to statuses. Migration 021 added `version` to all mutable entity tables. **SQL statement splitter:** `_split_sql_statements` uses `sqlite3.complete_statement` after stripping `-- ...` line comments, so semicolons inside string literals and line comments are safe. Block comments (`/* */`) are not stripped — avoid them in migration files.- **BaseEditModal pattern** — shared TUI modal base class providing save/cancel buttons, error display, `ctrl+n`/`ctrl+b` field navigation, `_do_save` (subclass hook), `_diff_and_dismiss` (edit modals), and `_parse_date_field` (date input validation). `_dismiss_callback` on `StxApp` wraps the null-check → try/except ValueError → notify → refresh pattern used by all modal callbacks.
- **MetadataModal** — single generic `MetadataModal(display_title, metadata, result_key, entity_id)` in `tui/screens/metadata.py` serves all three entity kinds (tasks, workspaces, groups). Reached via the `m` keybinding in `app.py::action_metadata`, which dispatches on the focused tree node's `.data` type (or the focused kanban card for tasks) to one of three `_open_*_metadata` builders. Each builder constructs the `display_title` + passes the entity's current metadata dict + a `result_key` (`task_id` / `workspace_id` / `group_id`). On save the modal dismisses with `{result_key: id, "metadata": new_dict}` and the corresponding `_on_*_metadata_dismiss` handler routes to `service.replace_*_metadata`. The modal's save-diff compares normalized (lowercase-keyed) forms so retyping a key's case alone is a no-op, matching the service-side normalization.
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
