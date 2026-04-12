ALTER TABLE tasks ADD COLUMN group_id INTEGER REFERENCES groups(id);

CREATE INDEX IF NOT EXISTS idx_tasks_group_id ON tasks(group_id);

UPDATE tasks SET group_id = (
    SELECT group_id FROM task_groups WHERE task_id = tasks.id
);

DROP TABLE task_groups;
