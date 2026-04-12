-- Replace task_history with unified journal table that covers all entity types.
-- Migrates existing task_history rows into journal (entity_type='task'),
-- then drops task_history.

CREATE TABLE journal (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type TEXT NOT NULL CHECK (entity_type IN (
        'task', 'project', 'group', 'workspace', 'status',
        'task_dependency', 'group_dependency'
    )),
    entity_id INTEGER NOT NULL,
    workspace_id INTEGER NOT NULL REFERENCES workspaces(id) ON DELETE RESTRICT,
    field TEXT NOT NULL,
    old_value TEXT,
    new_value TEXT,
    source TEXT NOT NULL,
    changed_at INTEGER NOT NULL DEFAULT (unixepoch())
);

CREATE INDEX idx_journal_entity
    ON journal(entity_type, entity_id, changed_at DESC, id DESC);

CREATE INDEX idx_journal_timeline
    ON journal(workspace_id, changed_at DESC);

INSERT INTO journal (id, entity_type, entity_id, workspace_id, field, old_value, new_value, source, changed_at)
    SELECT id, 'task', task_id, workspace_id, field, old_value, new_value, source, changed_at
    FROM task_history;

DROP TABLE task_history
