-- Remove group.done column. Added in 020 to back stx next and a planned
-- stx group done/undone CLI; neither was ever implemented. The column was
-- never rendered to users, never consulted by compute_next_tasks, and the
-- only consumer (group.updated hook on done flip) was broken (task-0161).
DROP INDEX IF EXISTS idx_groups_workspace_done;
ALTER TABLE groups DROP COLUMN done;
