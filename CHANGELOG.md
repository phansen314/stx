# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Removed
- **BREAKING:** tags feature removed. Tasks no longer have tags; the `tags` /
  `task_tags` tables are dropped, all `stx tag` subcommands are gone, and
  `--tag` / `--untag` flags are removed from `task create`, `task ls`, and
  `task edit`. `TaskListItem.tag_names`, `TaskDetail.tags`, and
  `WorkspaceContext.tags` are gone from JSON output. Use per-entity metadata
  JSON blobs if tagging-like grouping is needed.

### Migrations
- **017_drop_tags.sql.** Drops `tags` and `task_tags` tables plus their
  indexes. Historical `journal` rows with `entity_type='tag'`/`'task_tag'` are
  left untouched as dead history (`journal.entity_type` is an unconstrained
  TEXT column). `SCHEMA_VERSION = 17`.

### Changed
- **BREAKING:** `stx workspace rename` removed. Use `stx workspace edit --name <new>`.
  Operates on the active workspace or `-w` override (no more positional `old_name`).
- **BREAKING:** `stx group rename` removed. Use `stx group edit <title> --title <new>`.
  The `edit` verb is now the single mutation surface for group fields; `--dry-run`
  still previews the diff.
- **BREAKING:** `stx status rename` removed. Use `stx status edit <name> --name <new>`.
- **BREAKING:** `stx config unset` renamed to `stx config del`, matching the
  `del` verb family used by `{task,workspace,group} meta del`.
### Added
- `stx status show <name>` detail view, reporting the referencing task count
  alongside core fields.
- `stx group log <title>` and `stx workspace log` expose the unified journal
  for groups and workspaces (task `log` was already there). Presenter helper
  `format_task_history` renamed to `format_journal_entries` to reflect its
  entity-agnostic body.
- `stx workspace edit --dry-run` previews the diff without writing. Backed by
  new `service.preview_update_workspace` mirroring `preview_update_group`.

### Docs
- README no longer claims metadata is supported on every entity kind — statuses
  have no metadata column.
- CLAUDE.md brought forward to `SCHEMA_VERSION = 16` and the unified `edges` table
  (polymorphic endpoints, `acyclic` flag, collapsed `EntityType.EDGE`).

## [0.14.0] — 2026-04-13

### Added
- **Polymorphic edges.** `task_edges` + `group_edges` collapse into one
  `edges` table keyed on `(from_type, from_id, to_type, to_id, kind)`.
  Cross-type edges are now possible: task→group, group→workspace, etc.
  Multiple edge kinds between the same node pair are allowed (distinguished
  by `kind` in the PK).
- **Cycle detection (first implementation).** Reintroduced via recursive
  CTE `get_reachable_nodes` over `acyclic=1 AND archived=0` edges.
  `service.add_edge` runs the check when the new edge is acyclic. Design:
  all acyclic edges share one DAG regardless of kind — `blocks` + `spawns`
  cross-kind cycles are rejected. Non-acyclic edges (`informs`,
  `references`, `related-to`) can form cycles freely and don't participate
  in reachability.
- **Per-edge `acyclic` flag** with per-kind defaults: `blocks` / `spawns`
  default to `acyclic=1`, everything else defaults to `0`. CLI override
  via `stx edge create --acyclic` / `--no-acyclic`.
- **Typed node refs on the edge CLI.** `stx edge create --source task-0001
  --target group:foo --kind blocks` resolves mixed-type endpoints.
  `workspace:<name>` is also supported. `--source-parent` / `--target-parent`
  flags disambiguate groups with colliding titles under different parents.

### Changed
- **BREAKING:** `stx group edge …` removed. All edge commands unify under
  `stx edge create|archive|ls` and `stx edge meta ls|get|set|del`.
- **BREAKING:** Export JSON shape — `"task_edges"` + `"group_edges"` keys
  replaced by a single `"edges"` key whose rows carry `from_type`/`from_id`/
  `to_type`/`to_id` instead of `source_id`/`target_id`.
- **BREAKING:** Markdown export section heading: `### Task Edges` →
  `### Edges`. Mermaid block now mixes node shapes by type.
- **BREAKING:** `journal.entity_type` CHECK tightened to the new allowlist —
  rows with `'task_edge'` / `'group_edge'` are rewritten to `'edge'` by
  migration 016. `EntityType.TASK_EDGE` / `GROUP_EDGE` → `EntityType.EDGE`.
- **BREAKING:** `EdgeField.TARGET` → `EdgeField.ENDPOINT`. Edge endpoint
  identity in the journal is encoded as `"<from_type>:<from_id>→<to_type>:<to_id>"`
  on the `endpoint` field; `kind` is journaled on its own row.
- **BREAKING:** `TaskEdgeRef` / `GroupEdgeRef` / `TaskEdgeListItem` /
  `GroupEdgeListItem` → `EdgeRef` / `EdgeListItem`. Both carry a
  `NodeType = Literal["task","group","workspace"]` tagged union for
  endpoints. `TaskDetail.edge_sources` / `edge_targets` now yield
  `tuple[EdgeRef, ...]` that can point at any node type.
- **BREAKING:** `service.add_edge` / `archive_edge` take endpoint pairs as
  `(node_type, node_id)` tuples: `service.add_edge(conn, src, dst, *,
  kind, ...)`. Typo prevention — the old 4-arg signature made `from_id`/
  `to_id` swap-typos invisible.
- **BREAKING:** `MoveToWorkspacePreview.edge_ids: tuple[int, ...]` →
  `edge_endpoints: tuple[tuple[NodeType, int], ...]`. Task transfer dry-run
  JSON now reports typed endpoints so cross-type edges don't collide on ID.
- Cross-workspace edges are now rejected at the service layer (not via a
  DB FK). The unified edges table has no composite FK to endpoints because
  they are polymorphic; workspace alignment is checked in `service.add_edge`
  before insert.
- `stx edge create --kind BLOCKS` normalizes the kind to lowercase in the
  JSON output — previously CLI echoed the raw input while the DB stored
  the normalized form.

### Fixed
- `_validate_move_to_workspace` no longer blocks a task transfer when the
  only active edges point at archived endpoints. The unhydrated edge list
  functions join on the nodes CTE to match the hydrated + workspace-list
  behavior. Regression caught post-task-18, re-fixed.

### Migrations
- **016_unified_edges.sql.** Creates the new `edges` table, copies
  `task_edges` and `group_edges` into it with `acyclic=1` (all pre-016
  edges were dependency edges, which imply DAG semantics), drops the
  legacy tables, cascade-recreates `journal` to update its `entity_type`
  CHECK and rewrite old `task_edge` / `group_edge` rows to `edge`.
  `SCHEMA_VERSION = 16`.

## [0.13.0] — 2026-04-13

### Removed
- **BREAKING:** `projects` are removed as a first-class entity. Old projects
  become root groups (groups with `parent_id IS NULL`) via migration 015.
  `stx project *` subcommands are gone. `--project/-p` flags are dropped
  across `task create/ls/edit/mv/transfer` and `group *`. Group disambiguation
  is now title-only within a workspace (nested groups under different parents
  remain distinct).

### Added
- Optional `description` column on `groups`. Carried over from old project
  descriptions during migration.

### Changed
- `WorkspaceContext` no longer has a `projects` field. The TUI tree now
  renders `Workspace → root groups → subgroups → tasks`, with unassigned
  tasks (no `group_id`) shown at the workspace level.

## [0.12.0] — 2026-04-12

### Added

- **Kinded edges with per-edge metadata.** `task_dependencies` and `group_dependencies`
  tables replaced with `task_edges` and `group_edges`. Each edge carries a `kind TEXT`
  label (lowercase, `[a-z0-9_.-]+`, 1–64 chars, DB-enforced via CHECK) and a per-edge
  `metadata` JSON blob (same rules as entity metadata). `kind='blocks'` backfills the
  prior dependency semantics during migration.
- **`stx edge` command group.** Replaces `stx dep`: `stx edge create|archive|ls`,
  `stx edge meta ls|get|set|del`. Flags are `--source`, `--target`, `--kind`.
  `stx group edge …` mirrors the task surface with `--source-project` /
  `--target-project` for cross-project disambiguation.
- **Migration 014.** Renames the edge tables, backfills `kind='blocks'`, adds
  composite `UNIQUE (id, workspace_id)` to `groups` so `group_edges` can use a
  workspace-scoped composite FK (mirrors how `task_edges` anchors to `tasks`).
  Also recreates the `journal` table with updated `entity_type` CHECK covering
  `task_edge` / `group_edge`.
- **Workspace-scoped FK on group edges.** `group_edges.(source_id, workspace_id)`
  and `(target_id, workspace_id)` reference `groups(id, workspace_id)`. Cross-
  workspace group edges are now rejected at the DB layer, not just the service.
- **Archived-endpoint checks on edge create.** `add_task_edge` / `add_group_edge`
  raise a service-layer `ValueError` when either endpoint is archived, matching
  the convention already applied elsewhere (e.g. status/project/group assignment).
- **Schema `CHECK` on `kind`.** `CHECK (kind GLOB '[a-z0-9_.-]*' AND length(kind)
  BETWEEN 1 AND 64)` on both edge tables. Friendly error translation surfaces
  the rule when a raw-SQL violation slips through.

### Changed

- **`TaskDetail.blocked_by` / `blocks` → `edge_sources` / `edge_targets`**, each now a
  tuple of `TaskEdgeRef` `{task, kind}`. Breaking for JSON consumers of `stx task show`,
  `stx task create`, and friends. Symmetric change on `GroupDetail`.
- **JSON export keys renamed.** `task_dependencies` → `task_edges`,
  `group_dependencies` → `group_edges`. Each row now carries `source_id`, `target_id`,
  `workspace_id`, `archived`, `kind`, `metadata`.
- **`task transfer --dry-run`** renames `dependency_ids` → `edge_ids`.
- **Journal `entity_type`** values `task_dependency` / `group_dependency` renamed
  to `task_edge` / `group_edge`. Migration 014 rewrites existing rows via `CASE`
  in `INSERT SELECT`.
- **Schema version bumped to 14.**
- **`stx group edge ls`** uses `--source-project` (not `--project`) to disambiguate
  sources, matching `create` / `archive` / `meta *`. Breaking.
- **Edge listings filter archived endpoints.** `list_task_edges_by_workspace` and
  `list_group_edges_by_workspace` return only edges whose source and target are
  both active, matching the convention that archived entities stay hidden by default.
- **Repository edge metadata CRUD deduped** via `_EDGE_METADATA_TABLES` allowlist
  + generic `_get/_set/_remove/_replace_edge_metadata*` helpers mirroring the
  existing `_METADATA_TABLES` pattern for single-id entities. Public wrappers are
  one-line delegates.
- **Docs refreshed end-to-end** for the edge refactor: `docs/erd.md`,
  `docs/db-enforced-semantics.md`, `docs/service-enforced-semantics.md`,
  `README.md`, `CLAUDE.md`, `skills/stx/SKILL.md`,
  `skills/stx/references/cli-reference.md`, `skills/stx/references/json-schema.md`.

### Removed

- **Cycle detection.** Multi-hop cycles (A → B → C → A) are now allowed pending
  blocking-kind semantics rework — with `kind`-labelled edges, "cycle" is kind-
  dependent. The DB still rejects self-loops via `CHECK (source_id != target_id)`.
- **TUI dependency ordering.** The kanban board and workspace tree no longer
  topologically sort by edges; task/group order is insertion-order. Deferred
  along with cycle detection.
- **`stx dep` / `stx group dep` command groups.** Replaced by `stx edge` /
  `stx group edge`.

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

[Unreleased]: https://github.com/phansen314/stx/compare/v0.14.0...HEAD
[0.14.0]: https://github.com/phansen314/stx/compare/v0.13.0...v0.14.0
[0.13.0]: https://github.com/phansen314/stx/compare/v0.12.0...v0.13.0
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
