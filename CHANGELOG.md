# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

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

[Unreleased]: https://github.com/phansen314/sticky-notes/compare/v0.6.0...HEAD
[0.6.0]: https://github.com/phansen314/sticky-notes/releases/tag/v0.6.0
