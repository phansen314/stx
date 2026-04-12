# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.9.0] — 2026-04-11

### Added

- **TUI: status create modal.** Press `n` then `s` (or click `(s)tatus`) in the new-resource selector to create a status directly from the TUI. Fields: name and workspace (defaulted to the currently active workspace).
- **TUI: workspace create modal.** Press `n` then `w` (or click `(w)orkspace`) to create a new workspace from the TUI. Field: name.

## [0.8.0] — 2026-04-11

### Added

- **`todo config` command group.** `ls`, `get`, `set`, `unset` subcommands for managing TUI config. Editable fields: `auto_refresh_seconds` (positive integer) and `active_workspace` (workspace id or name). `todo config set active_workspace <name>` is equivalent to `todo workspace use <name>`. All fields are readable via `ls`/`get`; read is not restricted to the editable allowlist.

- **Active workspace migrated into `tui.toml`.** `active_workspace` is now stored as a field in `~/.config/sticky-notes/tui.toml` instead of a separate `~/.local/share/sticky-notes/active-workspace` file. The legacy file is still read as a fallback for one release; writes no longer go there.

- **TUI settings modal (`c` key).** Press `c` in the TUI to open an in-session settings editor for `theme` and `auto_refresh_seconds`. Changes apply live — theme swaps immediately, refresh timer is replaced without restart. Values are persisted to `tui.toml`. Also fixes a bug where the `theme` field in `tui.toml` was loaded but never actually applied to Textual's theme on startup.

- **TUI: kanban status columns are now focusable widgets.** Click a column or press up-arrow from the topmost task card to focus the column. Left/right arrows cycle focus between columns (wrapping); shift+left/right reorder the focused column (no wrap at edges). Column focus is indicated by a round green border, consistent with task card focus. Column order persists to `~/.config/sticky-notes/tui.toml` `status_order`.

- **TTY-aware output format.** CLI auto-detects whether stdout is a terminal: emits pretty text at a terminal, JSON when piped or redirected. Add `--json` to force JSON, `--text` to force text. Both flags are mutually exclusive. Archive commands now key off `sys.stdin.isatty()` for prompt gating — agents piping without `--force` receive an explicit error rather than silently auto-confirming.
- **`--text` global flag** — forces text output even when stdout is piped. Complements the existing `--json`.
- **`json-schema.md`** — new reference doc at `skills/sticky-notes/references/json-schema.md` documenting the `{ok, data}` envelope and per-command `data` shapes.
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
- **`todo status order <workspace> <status_1> <status_2> ...`** — CLI command to set the per-workspace status display order used by the TUI kanban board. Writes `~/.config/sticky-notes/tui.toml` via the existing `TuiConfig` module. Partial ordering is tolerated: unlisted statuses fall to the end in the TUI rendering. JSON payload: `{workspace_id, workspace, statuses: [{id, name}, ...]}`.
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

[Unreleased]: https://github.com/phansen314/sticky-notes/compare/v0.9.0...HEAD
[0.9.0]: https://github.com/phansen314/sticky-notes/compare/v0.8.0...v0.9.0
[0.8.0]: https://github.com/phansen314/sticky-notes/releases/tag/v0.8.0
[0.7.0]: https://github.com/phansen314/sticky-notes/releases/tag/v0.7.0

## [0.6.0] — 2026-04-10

### Added

- **Entity metadata for workspaces, projects, and groups.** Previously only tasks carried a JSON key/value metadata blob; now all four entity kinds do. CLI surface: `todo workspace meta ls|get|set|del`, `todo project meta ls|get|set|del <project>`, `todo group meta ls|get|set|del <title> [--project]`. Same lowercase key normalization, `[a-z0-9_.-]+` charset, 64-char key cap, and 500-char value cap as the existing task metadata.
- **TUI metadata editor** reached via the `m` keybinding. Works on any focused tree node (task / workspace / project / group) or kanban task card. Dynamic key/value rows with add/delete buttons, client-side duplicate-key detection, and atomic bulk-replace on save. A single generic `MetadataModal` class in `src/sticky_notes/tui/screens/metadata.py` serves all four entity kinds.
- **`replace_*_metadata` service API** for atomic multi-key writes: `replace_task_metadata`, `replace_workspace_metadata`, `replace_project_metadata`, `replace_group_metadata`. Per-key `set/remove_*_meta` helpers remain as the CLI surface; the bulk-replace surface backs the TUI modal. Both paths share the same normalization, duplicate detection, and value-length validation via the generic `_replace_entity_metadata` helper.
- **Pre-migration safety checks** in the migration runner (`_pre_migration_check`) to surface clear, actionable errors when a destructive DDL migration would otherwise fail with an opaque CHECK-constraint error — used by migration 011 to detect invalid task metadata JSON and off-allowlist `task_history.field` values before recreating the tables.

### Changed

- **Migration 011** retroactively adds `CHECK (json_valid(metadata))` to `tasks.metadata` (migration 010 omitted it) and adds metadata columns to `workspaces`, `projects`, and `groups`. The `tasks` table is recreated via the cascade-recreate pattern (`task_dependencies`, `task_tags`, `task_history` recreated alongside) to apply the new CHECK. The migration also retroactively adds `CHECK (field IN (...))` back to `task_history.field`, which migration 008 had dropped.
- **`Workspace` / `Project` / `Group` models** gain a required `metadata: dict[str, str]` field. Service models (`ProjectDetail`, `GroupDetail`, `GroupRef`) redeclare the field to match.
- **Markdown export** (`todo export --md`) now renders metadata under dedicated sections: an inline `**Metadata:**` block per workspace, plus `### Project Metadata`, `### Group Metadata`, and the existing `### Task Metadata`.

### Fixed

- Migration runner now restores `PRAGMA foreign_keys = ON` even when a migration fails, preventing the connection from being left with FKs disabled after a failed upgrade.

[0.6.0]: https://github.com/phansen314/sticky-notes/releases/tag/v0.6.0
