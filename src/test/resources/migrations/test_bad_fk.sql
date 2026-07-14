-- Test migration that leaves a dangling foreign key: with enforcement toggled OFF during a
-- migration, this row inserts, but `foreign_key_check` must catch it and roll the migration back
-- (data + version bump) rather than commit and advance user_version past a corrupt state.
INSERT INTO task (workspace_id, segment_id, status_id, title)
VALUES (999999, 999999, 999999, 'orphaned by a broken migration');
