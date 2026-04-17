-- Migration 022: forbid '/' and ':' in group/task titles.
--
-- Path-based ref syntax uses '/' as the group-segment delimiter and ':' as
-- the group-path → task-title delimiter (e.g. `A/B:my-task`). Existing rows
-- whose titles contain either char are renamed in a Python pre-step (see
-- connection._python_migration_022) before this SQL runs, so the dataset
-- entering this stamp is already clean.
--
-- This file is intentionally a no-op DDL stamp. The CHECK constraint that
-- enforces the rule going forward is in schema.sql for fresh databases;
-- pre-existing databases rely on service-layer validation
-- (service._validate_title) which is the single write path for both CLI and
-- TUI. Adding a runtime CHECK on tasks/groups would require a full table
-- recreate (cascading the FK web), which is not justified for a
-- defense-in-depth check the app layer already enforces.

SELECT 1;  -- stamp; user_version bump handled by the migration runner
