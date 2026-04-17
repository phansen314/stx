# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- **Path-based ref syntax for groups and tasks.** `/` is the group-segment
  delimiter, `:` is the group→task split, and a leading `/` is a Unix-style
  anchor that promotes single-segment refs to group paths. Examples:
  - `stx group show A/B/C` — strict walk from root to the C group under A/B.
  - `stx group show /A` — root group `A` (leading-slash anchor).
  - `stx task show A/B:leaf` — task `leaf` inside group `A/B`.
  - `stx task show :rootleaf` — root-level task (no group).
  - `stx task create -g A/B leaf` — create a task under a nested group via
    its path.
  - `stx group create A/B/new` — create `new` under existing parent path
    `A/B`. Mutually exclusive with `--parent`.
  - `stx edge create --source /A/B/C --target D:task0 --kind informs` —
    polymorphic edges infer endpoint type from delimiters: leading slash
    or multi-seg `/` → group, contains `:` → task, numeric → task by id,
    bare → task by title. The leading-slash anchor lets you reference a
    root group as `/A` without a `group:` prefix. Explicit prefixes
    `group:`/`task:`/`workspace:`/`status:` override inference.
  Bare titles still work; ambiguity (multi-match) errors as before, with a
  message suggesting a path ref.

### Changed

- **Breaking:** group and task titles can no longer contain `/` or `:` —
  both are reserved for path syntax. Existing rows are auto-renamed by
  migration 022 (`/` and `:` → `__`); collisions get a deterministic
  `__N` suffix. Each rename is journaled with `source='migration:022'`.
  Going forward the service layer rejects offending titles before any
  write; fresh databases also enforce the rule via a `CHECK` constraint
  in `schema.sql`.

### Removed

- **Breaking:** `stx edge` `--source-parent` and `--target-parent` flags
  are gone. Use a path ref in the suffix instead — e.g.
  `--source group:A/B` rather than `--source group:B --source-parent A`.
- **Breaking:** `service.resolve_group()` no longer accepts
  `parent_title=` / `parent_root=` keyword arguments. Pass a path ref as
  the positional argument.

## [0.14.0] — 2026-04-16

### Added

- **`stx:next` skill** — execution-focused Claude Code skill (invocable as
  `/next`). Pairs the `stx:stx` management skill: picks the highest-priority
  ready task from the dependency DAG via `stx next --rank`, hydrates it with
  task detail, group context, and downstream gate analysis, then presents a
  single work-order summary and offers to move the task to an in-progress
  status. Supports configurable edge kinds (`--edge-kind`) for workspaces that
  don't use the default `blocks` kind. Description rendering is truncated to
  the first 10 lines; task metadata is fetched on-demand via
  `stx --json task meta ls <task-id>` rather than rendered by default.

## [0.13.0] — 2026-04-14

### Added

- **`task.done` sticky completion flag.** Tasks now carry an explicit `done` boolean independent of status. `done` defaults to `false` on creation; it becomes `true` when a task is moved into a terminal status, or when created directly into one. Once set, `done` is sticky — it is not cleared by a status move (even out of a terminal status). Only `stx task undone [--force]` clears it. The flag is reflected in `task show` output, the kanban `[done]` marker, and `stx next` computation.

- **`status.is_terminal` flag.** Statuses can be marked terminal via `stx status edit <name> --terminal` / `--no-terminal`. When a task is moved into (or created in) a terminal status its `done` flag is auto-set to `true`. This is journaled with `source="auto"` so it is distinguishable from manual flips. Moving a task out of a terminal status does not clear `done` — it remains sticky.

- **`stx task done <task>`** — explicitly mark a task done (independent of status). True no-op (no write, no version bump) if already done.

- **`stx task undone <task> [--force]`** — clear the done flag. Gated: requires `--force` in non-interactive stdin; prompts y/N in a terminal. True no-op if already not done.

- **`stx next` command** — compute the next actionable tasks by topological sort of the active acyclic `blocks` edge DAG. Flags:
  - `--rank` — sort the ready list by (priority desc, due\_date asc, id asc)
  - `--include-blocked` — return the full topological order of all not-done tasks instead of just the ready frontier; `blocked` is empty in this mode
  - `--limit N` — cap the ready list to N items (applied after rank/topo sort)
  - `--edge-kind KIND` — repeatable; default `blocks`. Controls which edge kinds build the dependency DAG; only acyclic edges participate.

  Output has two sections: **Ready** (the frontier — tasks whose blockers are all done) and **Blocked** (not-done tasks with the task IDs of their pending blockers). Group endpoints in edges are expanded to their member task IDs, so a `group-A blocks group-B` edge means every not-done task in group-A must be done before any task in group-B becomes ready.

- **`stx status edit --terminal` / `--no-terminal`** — mutually exclusive flags to mark or unmark a status as terminal. Text output (`stx status ls`, `stx status show`) now includes a `[terminal]` marker and a `Terminal:` field respectively.

- **`group.done` read-only rollup.** A group's `done` field is automatically recomputed whenever a descendant task or group changes: it is `true` iff every non-archived child (direct task or subgroup) is done and the group is non-empty. The rollup fires post-commit in its own transaction so concurrent agents see the latest committed state. `group.done` is never set directly — it is a derived metric for display. `stx next` reads only `task.done`, never `group.done`.

- **Optimistic locking (version columns + CAS retries).** Every mutable entity table (`workspaces`, `statuses`, `groups`, `tasks`, `edges`) gains a `version INTEGER NOT NULL DEFAULT 0` column, incremented on every write by `_build_update` in `repository.py`. Write functions accept an optional `expected_version`; a version mismatch raises `ConflictError` (subclass of `ValueError`). The CLI `_with_cas_retry` helper re-fetches the entity and retries up to 3 times on conflict. Exit code 6 (`conflict`) is returned when retries are exhausted.

- **Task created into a terminal status starts as `done=True`.** Previously, a task created directly with `-S <terminal-status>` would show `done=false` even though it was in a completed status. Creation now checks `is_terminal` and sets the initial `done` flag accordingly.

### Schema

- **Migration 020** (`020_done_flags.sql`): `ALTER TABLE statuses ADD COLUMN is_terminal INTEGER NOT NULL DEFAULT 0 CHECK (is_terminal IN (0, 1))`. `ALTER TABLE tasks ADD COLUMN done INTEGER NOT NULL DEFAULT 0 CHECK (done IN (0, 1))`. `ALTER TABLE groups ADD COLUMN done INTEGER NOT NULL DEFAULT 0 CHECK (done IN (0, 1))`. Two new indexes: `idx_tasks_workspace_done ON tasks(workspace_id, done, archived)` and `idx_groups_workspace_done ON groups(workspace_id, done, archived)`.

- **Migration 021** (`021_version_columns.sql`): `ALTER TABLE {workspaces,statuses,groups,tasks,edges} ADD COLUMN version INTEGER NOT NULL DEFAULT 0`. All five are simple `ALTER TABLE` statements — no table recreate. `SCHEMA_VERSION` advances from 19 → 21.

## [0.12.0] — 2026-04-13

### Added

- **Polymorphic kinded edges with per-edge metadata.** The old
  `task_dependencies` / `group_dependencies` tables collapse into a single
  `edges` table keyed on `(from_type, from_id, to_type, to_id, kind)`.
  Endpoints can be `task`, `group`, `workspace`, or `status` — cross-type
  edges are supported (task→group, group→workspace, status→status, etc.).
  Each edge carries a `kind TEXT` label (lowercase, `[a-z0-9_.-]+`, 1–64
  chars, DB-enforced via CHECK), a per-edge `metadata` JSON blob (same
  rules as entity metadata), and an `acyclic` flag. Multiple edge kinds
  between the same node pair are allowed (distinguished by `kind` in the
  primary key). `kind='blocks'` backfills the prior dependency semantics.
- **Cycle detection** on acyclic edges via a recursive-CTE
  `get_reachable_nodes` over `acyclic=1 AND archived=0` rows.
  `service.add_edge` runs the check when the new edge is acyclic. All
  acyclic edges share one DAG regardless of kind — `blocks` + `spawns`
  cross-kind cycles are rejected. Non-acyclic edges (`informs`,
  `references`, `related-to`) can form cycles freely and don't participate
  in reachability.
- **Per-edge `acyclic` flag** with per-kind defaults: `blocks` / `spawns`
  default to `acyclic=1`, everything else defaults to `0`. CLI override
  via `stx edge create --acyclic` / `--no-acyclic`.
- **`stx edge` command group.** Unified, polymorphic replacement for
  `stx dep`: `stx edge create|archive|ls|show|edit|log` and `stx edge meta
  ls|get|set|del`. Endpoint refs are typed: `stx edge create --source
  task-0001 --target group:foo --kind blocks`; `workspace:<name>` and
  `status:<name>` are also supported. `--source-parent` /
  `--target-parent` disambiguate groups with colliding titles under
  different parents.
- **`stx edge show`** — full detail view for a single edge, including
  endpoint titles, `acyclic` / `archived` flags, metadata, and filtered
  journal history.
- **`stx edge edit`** — mutate the `acyclic` flag on an existing edge.
  Kind and endpoints are immutable (composite PK). Flipping `0 → 1`
  re-runs cycle detection and rejects the edit if a cycle would result.
- **`stx edge log`** — journal history for a single edge, recovered via
  paired endpoint/kind rows sharing a transaction timestamp.
- **Archived-endpoint checks on edge create.** `service.add_edge` raises
  `ValueError` when either endpoint is archived, matching the convention
  already applied elsewhere (status/group assignment, etc.).
- **`stx task edit --group <title>`** assigns a task to a group; pass an
  empty string (`--group ""`) to unassign. Complements the existing
  `stx group assign` / `stx group unassign` — both routes funnel through
  `service.update_task` / `_update_task_body`.
- **`stx status show <name>`** — detail view reporting the referencing
  task count alongside core fields.
- **`stx group log <title>` / `stx workspace log`** expose the unified
  journal for groups and workspaces (task `log` was already there).
  Presenter helper `format_task_history` renamed to
  `format_journal_entries` to reflect its entity-agnostic body.
- **`stx workspace edit --dry-run`** previews the diff without writing.
  Backed by new `service.preview_update_workspace` mirroring
  `preview_update_group`.
- **Optional `description` column on `groups`.** Carried over from old
  project descriptions during the projects-removal migration.

### Changed

- **BREAKING:** `TaskDetail.blocked_by` / `blocks` → `edge_sources` /
  `edge_targets`, each a tuple of `EdgeRef` `{node_type, node_id, kind}`.
  Symmetric change on `GroupDetail`. Breaking for JSON consumers of
  `stx task show`, `stx task create`, and siblings.
- **BREAKING:** `TaskEdgeRef` / `GroupEdgeRef` / `TaskEdgeListItem` /
  `GroupEdgeListItem` → `EdgeRef` / `EdgeListItem`. Both carry a
  `NodeType = Literal["task","group","workspace","status"]` tagged union
  for endpoints.
- **BREAKING:** `service.add_edge` / `archive_edge` take endpoint pairs
  as `(node_type, node_id)` tuples: `service.add_edge(conn, src, dst, *,
  kind, ...)`. Typo prevention — the old 4-arg signature made
  `from_id`/`to_id` swap-typos invisible.
- **BREAKING:** Export JSON shape — `"task_dependencies"` /
  `"group_dependencies"` collapse into a single `"edges"` key whose rows
  carry `from_type` / `from_id` / `to_type` / `to_id`, `kind`,
  `metadata`, `acyclic`, `archived`, `workspace_id`.
- **BREAKING:** Markdown export section heading: `### Task Dependencies`
  → `### Edges`. Mermaid block now mixes node shapes by type.
- **BREAKING:** `journal.entity_type` CHECK tightened to the new
  allowlist — rows with `'task_dependency'` / `'group_dependency'` /
  `'task_edge'` / `'group_edge'` are all rewritten to `'edge'` by
  migrations 014 and 016. `EntityType.TASK_EDGE` / `GROUP_EDGE` →
  `EntityType.EDGE`.
- **BREAKING:** `EdgeField.TARGET` → `EdgeField.ENDPOINT`. Edge endpoint
  identity in the journal is encoded as
  `"<from_type>:<from_id>→<to_type>:<to_id>"` on the `endpoint` field;
  `kind` is journaled on its own row.
- **BREAKING:** `MoveToWorkspacePreview.edge_ids: tuple[int, ...]` →
  `edge_endpoints: tuple[tuple[NodeType, int], ...]`. Task transfer
  dry-run JSON now reports typed endpoints so cross-type edges don't
  collide on ID.
- **BREAKING:** `task transfer --dry-run` renames `dependency_ids` →
  `edge_ids`.
- **BREAKING:** `stx workspace rename` removed. Use
  `stx workspace edit --name <new>` — operates on the active workspace
  or `-w` override (no more positional `old_name`).
- **BREAKING:** `stx group rename` removed. Use
  `stx group edit <title> --title <new>`. The `edit` verb is now the
  single mutation surface for group fields; `--dry-run` still previews
  the diff.
- **BREAKING:** `stx status rename` removed. Use
  `stx status edit <name> --name <new>`.
- **BREAKING:** `stx config unset` renamed to `stx config del`, matching
  the `del` verb family used by `{task,workspace,group} meta del`.
- **`WorkspaceContext`** no longer has a `projects` field. The TUI tree
  now renders `Workspace → root groups → subgroups → tasks`, with
  unassigned tasks (no `group_id`) shown at the workspace level.
- **Cross-workspace edges** are rejected at the service layer (not via a
  DB FK). The unified `edges` table has no composite FK to endpoints
  because they are polymorphic; workspace alignment is checked in
  `service.add_edge` before insert.
- **`stx edge create --kind BLOCKS`** normalizes the kind to lowercase in
  the JSON output — previously CLI echoed the raw input while the DB
  stored the normalized form.
- **`stx status archive --force`** now emits a stderr warning line when
  active tasks will be cascade-archived (parity with task / group /
  workspace prompts — informational only, not a prompt, preserves
  pipe-friendliness).
- **Edge listings filter archived endpoints.** `list_edges_by_workspace`
  joins against a nodes CTE and returns only edges whose source and
  target are both active, matching the convention that archived entities
  stay hidden by default.
- **Docs refreshed end-to-end** for the edge / project / tag / position
  refactors: `docs/erd.md`, `docs/db-enforced-semantics.md`,
  `docs/service-enforced-semantics.md`, `README.md`, `CLAUDE.md`,
  `skills/stx/SKILL.md`, `skills/stx/references/cli-reference.md`,
  `skills/stx/references/json-schema.md`.

### Fixed

- **`_validate_move_to_workspace` no longer blocks a task transfer** when
  the only active edges point at archived endpoints. The unhydrated edge
  list functions now join on the nodes CTE to match the hydrated +
  workspace-list behavior.
- **`archive_status` bulk task moves bypassed the journal.** When
  archiving a status with `--reassign-to` or `--force`, every affected
  task was updated via `repo.update_task` without emitting a `TASK`
  journal entry. The status row itself was journaled, leaving a silent
  audit gap. Task reassignment and force-archive now record per-task
  `status_id` / `archived` entries via `_record_entity_changes`, and the
  reassign path validates the target status (same workspace, not
  archived) before touching tasks.
- **`_get_entity_meta` raised `AttributeError` on deleted entities.**
  Siblings defensively checked `if entity is None` before reading
  `.metadata`; this one did not, so `stx <entity> meta get` on a
  nonexistent id crashed instead of raising `LookupError`.
- **TUI auto-refresh reloaded the full workspace every tick** regardless
  of whether anything changed. Timer-driven refreshes now read
  `PRAGMA data_version` and short-circuit when the value is unchanged
  since the last tick. Manual `r`-key refresh still always reloads.
- **Connection `busy_timeout` was unset.** `get_connection` now passes
  `timeout=30.0` to `sqlite3.connect` and issues
  `PRAGMA busy_timeout = 30000` alongside `foreign_keys` /
  `journal_mode`. Under TUI + CLI contention the previous 5 s default
  surfaced as `database is locked` errors with no retry window.
- **SQL statement splitter could slice mid-definition.** `connection.py`
  migration and schema loading no longer use `sql.split(";")`, which
  broke when a semicolon appeared inside a string literal or line
  comment. The new `_split_sql_statements` accumulates lines through
  `sqlite3.complete_statement` after stripping `-- ...` comments.

### Removed

- **BREAKING:** `projects` as a first-class entity. Old projects become
  root groups (groups with `parent_id IS NULL`) via migration 015.
  `stx project *` subcommands are gone. `--project/-p` flags are dropped
  across `task create/ls/edit/mv/transfer` and `group *`. Group
  disambiguation is now title-only within a workspace (nested groups
  under different parents remain distinct).
- **BREAKING:** `tags` feature. Tasks no longer carry tags; the `tags` /
  `task_tags` tables are dropped, all `stx tag` subcommands are gone, and
  `--tag` / `--untag` flags are removed from `task create`, `task ls`,
  and `task edit`. `TaskListItem.tag_names`, `TaskDetail.tags`, and
  `WorkspaceContext.tags` are gone from JSON output. Use per-entity
  metadata JSON blobs if tagging-like grouping is needed.
- **BREAKING:** `position` column on `tasks` and `groups`. The field was
  defaulted to 0 for every row, no TUI surface wrote it, and the
  cross-workspace transfer reset it anyway — ordering effectively
  collapsed to insertion order. `stx task mv` no longer accepts
  `--position` or the legacy positional position argument,
  `TaskMovePreview` drops `from_position` / `to_position`, and task /
  group JSON no longer includes a `position` field. Task and group list
  order is now `id ASC`.
- **TUI dependency ordering.** The kanban board and workspace tree no
  longer topologically sort by edges; task / group order is
  insertion-order.
- **`stx dep` / `stx group dep` command groups.** Replaced by the
  unified `stx edge` surface.

### Migrations

- **014_task_edges.sql.** Renames `task_dependencies` /
  `group_dependencies` to `task_edges` / `group_edges`, backfills
  `kind='blocks'`, adds composite `UNIQUE (id, workspace_id)` to
  `groups` so `group_edges` can use a workspace-scoped composite FK
  (mirrors how `task_edges` anchors to `tasks`), and recreates `journal`
  with an updated `entity_type` CHECK covering the new edge entity
  names.
- **015_remove_projects.sql.** Folds old projects into root groups
  (`parent_id IS NULL`) preserving title, description, and workspace
  association, then drops the `projects` table.
- **016_unified_edges.sql.** Creates the polymorphic `edges` table,
  copies `task_edges` + `group_edges` into it with `acyclic=1` (all
  pre-016 edges were dependency edges, which imply DAG semantics),
  drops the legacy tables, and cascade-recreates `journal` to rewrite
  old `task_edge` / `group_edge` rows to `edge`.
- **017_drop_tags.sql.** Drops `tags` and `task_tags` tables plus their
  indexes. Historical `journal` rows with `entity_type='tag'` /
  `'task_tag'` are left untouched as dead history
  (`journal.entity_type` is an unconstrained TEXT column).
- **018_drop_position.sql.** Cascade-recreates `tasks` and `groups`
  without the `position` column, replaces the four
  `*_archived_position` covering indexes with `*_archived` variants,
  and preserves all row data. Historical `journal` rows with
  `field='position'` are left intact as dead history.
- **019_status_edges.sql.** Widens the `edges.from_type` / `to_type`
  CHECK constraints to include `'status'` so statuses can act as
  polymorphic edge endpoints. No data migration needed — existing rows
  are unaffected. `SCHEMA_VERSION = 19`.

## [0.11.0] — 2026-04-12

### Added

- **Unified journal table.** Replaces the task-scoped `task_history` table with a
  `journal` table covering all entity types: `task`, `project`, `group`, `workspace`,
  `status`, `task_dependency`, and `group_dependency`. Field changes, dependency
  link/unlink events, and metadata key-level diffs are all recorded in one table with
  `entity_type`, `entity_id`, `field`, `old_value`, `new_value`, `source`, and
  `changed_at` columns. Cross-entity timeline queries now work without JOINs.
- **Metadata journaling.** `stx {task,workspace,project,group} meta set/del` and the
  TUI metadata bulk-replace now emit per-key journal entries (field `meta.<key>`).
- **Dependency journaling.** `stx dep create/archive` and `stx group dep create/archive`
  emit journal entries (`field = "depends_on"`, `entity_type = "task_dependency"` /
  `"group_dependency"`).
- **`source` parameter on update/archive functions.** All mutation functions now accept
  a `source` keyword argument (`"cli"` default, `"tui"` from TUI event handlers).
- **Migration 013.** Existing `task_history` rows are migrated into `journal` with
  `entity_type = 'task'`. The `task_history` table is then dropped.

### Changed

- **`stx export --json`** now uses key `"journal"` instead of `"task_history"`.
- **Schema version** bumped to 13.

## [0.9.0] — 2026-04-11

### Added

- **TUI: status create modal.** Press `n` then `s` (or click `(s)tatus`) in the new-resource selector to create a status directly from the TUI. Fields: name and workspace (defaulted to the currently active workspace).
- **TUI: workspace create modal.** Press `n` then `w` (or click `(w)orkspace`) to create a new workspace from the TUI. Field: name.

## [0.8.0] — 2026-04-11

### Added

- **`todo config` command group.** `ls`, `get`, `set`, `unset` subcommands for managing TUI config. Editable fields: `auto_refresh_seconds` (positive integer) and `active_workspace` (workspace id or name). `todo config set active_workspace <name>` is equivalent to `todo workspace use <name>`. All fields are readable via `ls`/`get`; read is not restricted to the editable allowlist.

- **Active workspace migrated into `tui.toml`.** `active_workspace` is now stored as a field in `~/.config/stx/tui.toml` instead of a separate `~/.local/share/stx/active-workspace` file. The legacy file is still read as a fallback for one release; writes no longer go there.

- **TUI settings modal (`c` key).** Press `c` in the TUI to open an in-session settings editor for `theme` and `auto_refresh_seconds`. Changes apply live — theme swaps immediately, refresh timer is replaced without restart. Values are persisted to `tui.toml`. Also fixes a bug where the `theme` field in `tui.toml` was loaded but never actually applied to Textual's theme on startup.

- **TUI: kanban status columns are now focusable widgets.** Click a column or press up-arrow from the topmost task card to focus the column. Left/right arrows cycle focus between columns (wrapping); shift+left/right reorder the focused column (no wrap at edges). Column focus is indicated by a round green border, consistent with task card focus. Column order persists to `~/.config/stx/tui.toml` `status_order`.

- **TTY-aware output format.** CLI auto-detects whether stdout is a terminal: emits pretty text at a terminal, JSON when piped or redirected. Add `--json` to force JSON, `--text` to force text. Both flags are mutually exclusive. Archive commands now key off `sys.stdin.isatty()` for prompt gating — agents piping without `--force` receive an explicit error rather than silently auto-confirming.
- **`--text` global flag** — forces text output even when stdout is piped. Complements the existing `--json`.
- **`json-schema.md`** — new reference doc at `skills/stx/references/json-schema.md` documenting the `{ok, data}` envelope and per-command `data` shapes.
- **`task transfer --dry-run` JSON now includes `target_project_id`** (`null` when `--project` not passed). Previously omitted even when `--project` was supplied.
- **`workspace show [name]`** accepts an optional workspace name positional, matching `workspace archive`. Defaults to active workspace / `-w`.

### Changed

- **TUI: up-arrow from the top card no longer wraps to the bottom card** — it focuses the containing status column. Down-arrow from the bottom card is now a no-op (previously wrapped to top).

### Fixed

- **TUI: focus blip when moving a task across statuses** (`shift+left/right` on a focused task card). Focus briefly jumped to the containing `KanbanColumn` before snapping back to the card in its new column, causing a visible highlight flash. `_sync_cards` now pre-clears focus before removing the focused card so Textual has nothing to auto-relocate to.
- **TUI: workspace switch reverted kanban columns to alphabetical order.** `on_workspace_tree_workspace_changed` called `tree.load()` after switching, which re-posted a `WorkspaceChanged` for the first workspace in insertion order; the re-entrant handler clobbered the kanban with the wrong workspace's model (no `status_order` applied). The redundant `tree.load()` is gone — the user's own tree navigation already leaves the tree in the correct state.

- **`task ls --json`** returns `[{"status": {...}, "tasks": [...]}]` — a flat array of per-status buckets, each containing a full Status object and a `tasks` array of TaskListItem objects. Text output is unchanged. Use `workspace show` for the richer kanban context view (projects, tags, groups). Breaking from the prior `{workspace, statuses}` nested shape.
- **`group assign` and `group unassign` `--json` now return full TaskDetail** instead of `{task, group_id}` wrapper. Hydrated `group` object includes `title`. Breaking.
- **`dep create/archive` `--json` field names renamed** to match flag framing: `task_id` → `blocked_task_id`, `depends_on_id` → `blocking_task_id`. Group-dep analogously: `group_id` → `blocked_group_id`, `depends_on_id` → `blocking_group_id`. Breaking.
- **`task edit`, `task mv`, `task archive` `--json` now return full TaskDetail** (same shape as `task show`) instead of a bare Task. Breaking for JSON consumers reading `status_id` directly — it is now `status.id`. Agents no longer need a follow-up `task show` call after mutations. (`task transfer` returns `{"task": TaskDetail, "source_task_id": N}` — see transfer entry above.)
- **`status order` no longer takes a workspace positional.** Uses active workspace / `-w` flag like every other workspace-scoped command. Breaking: `todo status order dev backlog done` → `todo status order backlog done`.
- **`status ls` and `project ls` accept `--archived hide|include|only`** (default `hide`). Mirrors the filter already on `workspace ls`, `tag ls`, and `group ls`.
- **`status archive --force`** no longer enters the confirmation prompt. `--force` and `--reassign-to` both proceed without prompting — matching the behavior of every other archive command. Previously `--force` triggered the prompt loop, which raised an error on non-TTY stdin despite `--force` already being passed.

## [0.7.0] — 2026-04-10

### Added

- **`--dry-run` on edit commands.** `task edit`, `task mv`, `project edit`, `group edit`, `group rename`, and `group mv` now accept `--dry-run` to preview the diff (or the from/to snapshot for `task mv`) without writing to the database. Preview output includes before/after values for changed fields; tag adds/removes surface under `+tag`/`-tag` lines for `task edit`. New service helpers: `preview_update_task`, `preview_move_task`, `preview_update_project`, `preview_update_group`. JSON shapes: `EntityUpdatePreview` and `TaskMovePreview`. For `group mv` / `group rename` dry-runs, the `parent_id` diff renders parent group titles via a per-key resolver rather than exposing raw ids — key in `before` / `after` stays `parent_id`, values are title strings.
- **`todo status order <workspace> <status_1> <status_2> ...`** — CLI command to set the per-workspace status display order used by the TUI kanban board. Writes `~/.config/stx/tui.toml` via the existing `TuiConfig` module. Partial ordering is tolerated: unlisted statuses fall to the end in the TUI rendering. JSON payload: `{workspace_id, workspace, statuses: [{id, name}, ...]}`.
- **`tag rename <old> <new>`** and **`project rename <old> <new>`** subcommands. The rename pattern is now uniform across workspace / status / project / group / tag — all take two positionals. Backs a new `service.update_tag` wrapper.
- **Distinct exit codes** for CLI errors. Previously all user-facing errors collapsed to exit `1`; they now split into `3` (`not_found`), `4` (`validation`), and `5` (`missing_active_workspace`). `2` (db error) is unchanged. Scripts can now distinguish error classes without parsing `--json`.
- **Non-TTY confirmation guard** on archive commands. Piped or CI invocations of `task archive` / `group archive` / etc. without `--force` or `--dry-run` now fail fast with a clear validation error instead of hanging on `input()` or crashing on EOF.

### Changed

- **`group mv`** replaces the `--parent ''` magic sentinel with an explicit `--to-top` flag. `--parent TITLE` and `--to-top` are now mutually exclusive and one is required. Breaking.
- **`todo export -o FILE`** now refuses to clobber an existing file unless `--overwrite` is passed. Matches the `todo backup` contract. Breaking for scripts that relied on silent overwrite.
- **`todo group-dep`** moved under `todo group dep`. The top-level hyphenated verb is gone; use `todo group dep create` / `todo group dep archive` instead. Breaking.
- **`todo dep create` / `todo dep archive`** now take `--task TASK --blocked-by TASK` flags instead of two positional arguments. Removes the "which came first, the blocker or the blocked?" ambiguity. Breaking.
- **`todo group dep create` / `todo group dep archive`** now take `--group TITLE --blocked-by TITLE` flags instead of two positional arguments. Matches `dep create`'s shape. Breaking.
- **`--by-title` flag removed** from every task-referencing command. Task identifiers are now auto-detected: numeric forms (`1`, `task-0001`, `#1`) resolve as IDs; everything else is looked up as a title on the active workspace. Affects `task show/edit/mv/transfer/archive/log`, `task meta ls/get/set/del`, `dep create/archive`, `group assign/unassign`. Breaking for scripts that passed `--by-title` explicitly. A task whose title literally matches `task-NNNN` would be resolved as an ID — avoid such titles.
- **`todo task mv` status argument is now a required flag** (`--status` / `-S`) instead of a second positional. Matches the `task create` / `task transfer` shape. Optional `position` remains a positional integer after the task identifier. Breaking.
- **`task ls`, `workspace ls`, `tag ls`, and `group ls` replace `--all`/`--archived` booleans with a single tri-state `--archived {hide,include,only}`** (default `hide`). `--all`/`-a` is gone; the previous boolean `--archived` meaning "only archived" now requires `--archived only`. Breaking.
- **`group ls --tree` removed.** The tree-rendering CLI mode is gone — the TUI's left panel already renders the workspace hierarchy interactively, and `todo workspace show --json` dumps the structured data for scripting. `build_group_tree`, `format_group_trees`, `GroupTreeNode`, and `ProjectGroupTree` are all deleted. Breaking for any scripts using `group ls --tree`.
- **`todo context` renamed to `todo workspace show`.** Same data shape and semantics, moved under the `workspace` subparser for discoverability. Breaking — scripts must update the command invocation. Help text is now reachable via `todo workspace --help`.
- **`todo workspace archive --json` payload reshaped** to `{"workspace": {...}, "active_cleared": bool}`. Surfaces the active-pointer side-effect so JSON consumers don't have to re-query. Text output gains a trailing `(active pointer cleared)` suffix when applicable. Breaking for JSON consumers that read the flat Workspace object.
- **`todo info --json` payload reshaped.** Each file entry is now `{"path": str, "exists": bool}` instead of four flat strings plus an `existing` array subset. Text output is unchanged. Breaking for JSON consumers.
- **Priority is now an unconstrained integer.** Migration 012 drops the `CHECK (priority BETWEEN 1 AND 5)` constraint on `tasks.priority`; service-layer range validation is gone. Interpretation (direction, labels) is the user's concern — use entity metadata if a fixed scheme is needed. Default stays at `1`. Behaviour relaxation rather than a breaking change: inputs that used to error now succeed.
- **`task create --json`** now returns a full `TaskDetail` (same shape as `task show`) instead of a bare `Task`. Tags attached via `--tag` are finally visible in the response — previously the raw `Task` object had no `tags` field and the footnote in the reference documented the gap.
- **`task transfer --workspace`** renamed to **`task transfer --to`**. The old name collided with the global `-w/--workspace` flag (which selects the *source* workspace). `--to` is unambiguous. Breaking.
- **`workspace rename`** now requires both `old` and `new` positional arguments. The previous 1-arg mode ("rename active workspace") silently renamed the active workspace when the user usually meant to rename a named one. Breaking.
- **`project edit --name/-n`** removed; use the new `project rename` instead. `project edit` now only handles description changes.
- **Dropped `-P` / `-s` short flags** from `task create` / `task ls` / `task edit`. They case-collided with `-p` (project) and `-S` (status), making shift-key typos silently do the wrong thing. Long forms `--priority` and `--search` remain. Breaking for any script relying on the shorts.

[Unreleased]: https://github.com/phansen314/stx/compare/v0.12.0...HEAD
[0.12.0]: https://github.com/phansen314/stx/compare/v0.11.0...v0.12.0
[0.11.0]: https://github.com/phansen314/stx/compare/v0.10.0...v0.11.0
[0.10.0]: https://github.com/phansen314/stx/compare/v0.9.0...v0.10.0
[0.9.0]: https://github.com/phansen314/stx/compare/v0.8.0...v0.9.0
[0.8.0]: https://github.com/phansen314/stx/releases/tag/v0.8.0
[0.7.0]: https://github.com/phansen314/stx/releases/tag/v0.7.0

## [0.6.0] — 2026-04-10

### Added

- **Entity metadata for workspaces, projects, and groups.** Previously only tasks carried a JSON key/value metadata blob; now all four entity kinds do. CLI surface: `todo workspace meta ls|get|set|del`, `todo project meta ls|get|set|del <project>`, `todo group meta ls|get|set|del <title> [--project]`. Same lowercase key normalization, `[a-z0-9_.-]+` charset, 64-char key cap, and 500-char value cap as the existing task metadata.
- **TUI metadata editor** reached via the `m` keybinding. Works on any focused tree node (task / workspace / project / group) or kanban task card. Dynamic key/value rows with add/delete buttons, client-side duplicate-key detection, and atomic bulk-replace on save. A single generic `MetadataModal` class in `src/stx/tui/screens/metadata.py` serves all four entity kinds.
- **`replace_*_metadata` service API** for atomic multi-key writes: `replace_task_metadata`, `replace_workspace_metadata`, `replace_project_metadata`, `replace_group_metadata`. Per-key `set/remove_*_meta` helpers remain as the CLI surface; the bulk-replace surface backs the TUI modal. Both paths share the same normalization, duplicate detection, and value-length validation via the generic `_replace_entity_metadata` helper.
- **Pre-migration safety checks** in the migration runner (`_pre_migration_check`) to surface clear, actionable errors when a destructive DDL migration would otherwise fail with an opaque CHECK-constraint error — used by migration 011 to detect invalid task metadata JSON and off-allowlist `task_history.field` values before recreating the tables.

### Changed

- **Migration 011** retroactively adds `CHECK (json_valid(metadata))` to `tasks.metadata` (migration 010 omitted it) and adds metadata columns to `workspaces`, `projects`, and `groups`. The `tasks` table is recreated via the cascade-recreate pattern (`task_dependencies`, `task_tags`, `task_history` recreated alongside) to apply the new CHECK. The migration also retroactively adds `CHECK (field IN (...))` back to `task_history.field`, which migration 008 had dropped.
- **`Workspace` / `Project` / `Group` models** gain a required `metadata: dict[str, str]` field. Service models (`ProjectDetail`, `GroupDetail`, `GroupRef`) redeclare the field to match.
- **Markdown export** (`todo export --md`) now renders metadata under dedicated sections: an inline `**Metadata:**` block per workspace, plus `### Project Metadata`, `### Group Metadata`, and the existing `### Task Metadata`.

### Fixed

- Migration runner now restores `PRAGMA foreign_keys = ON` even when a migration fails, preventing the connection from being left with FKs disabled after a failed upgrade.

[0.6.0]: https://github.com/phansen314/stx/releases/tag/v0.6.0
