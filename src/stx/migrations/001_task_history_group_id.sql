ALTER TABLE task_history RENAME TO _task_history_old;

CREATE TABLE task_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL REFERENCES tasks(id),
    field TEXT NOT NULL CHECK (field IN (
        'title', 'description', 'column_id', 'project_id',
        'priority', 'due_date', 'position', 'archived',
        'start_date', 'finish_date', 'group_id'
    )),
    old_value TEXT,
    new_value TEXT NOT NULL,
    source TEXT NOT NULL,
    changed_at INTEGER NOT NULL DEFAULT (unixepoch())
);

INSERT INTO task_history (id, task_id, field, old_value, new_value, source, changed_at)
SELECT id, task_id, field, old_value, new_value, source, changed_at FROM _task_history_old;

DROP TABLE _task_history_old;

CREATE INDEX IF NOT EXISTS idx_task_history_task_id ON task_history(task_id);
