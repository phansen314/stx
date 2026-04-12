-- Rename columns table to statuses, dropping position
ALTER TABLE columns RENAME TO _columns_old;
CREATE TABLE statuses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    board_id INTEGER NOT NULL REFERENCES boards(id) ON DELETE RESTRICT,
    name TEXT NOT NULL COLLATE NOCASE,
    archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)),
    created_at INTEGER NOT NULL DEFAULT (unixepoch()),
    UNIQUE (id, board_id)
);
INSERT INTO statuses (id, board_id, name, archived, created_at)
SELECT id, board_id, name, archived, created_at FROM _columns_old;
DROP TABLE _columns_old;

-- Rename tasks.column_id to status_id
ALTER TABLE tasks RENAME TO _tasks_old;
CREATE TABLE tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    board_id INTEGER NOT NULL,
    project_id INTEGER,
    title TEXT NOT NULL COLLATE NOCASE,
    description TEXT,
    status_id INTEGER NOT NULL,
    priority INTEGER NOT NULL DEFAULT 1 CHECK (priority BETWEEN 1 AND 5),
    due_date INTEGER,
    position INTEGER NOT NULL DEFAULT 0 CHECK (position >= 0),
    archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)),
    created_at INTEGER NOT NULL DEFAULT (unixepoch()),
    start_date INTEGER,
    finish_date INTEGER,
    group_id INTEGER,
    CHECK (start_date IS NULL OR finish_date IS NULL OR finish_date >= start_date),
    CHECK (group_id IS NULL OR project_id IS NOT NULL),
    FOREIGN KEY (status_id, board_id) REFERENCES statuses(id, board_id) ON DELETE RESTRICT,
    FOREIGN KEY (project_id, board_id) REFERENCES projects(id, board_id) ON DELETE RESTRICT,
    FOREIGN KEY (board_id) REFERENCES boards(id) ON DELETE RESTRICT,
    FOREIGN KEY (group_id, project_id) REFERENCES groups(id, project_id) ON DELETE RESTRICT,
    UNIQUE (id, board_id)
);
INSERT INTO tasks
(id, board_id, project_id, title, description, status_id, priority,
due_date, position, archived, created_at, start_date, finish_date, group_id)
SELECT id, board_id, project_id, title, description, column_id, priority,
due_date, position, archived, created_at, start_date, finish_date, group_id
FROM _tasks_old;
DROP TABLE _tasks_old;

-- Recreate task_history with updated CHECK constraint
-- (rename first to avoid violating old CHECK when transforming field values)
ALTER TABLE task_history RENAME TO _task_history_old;
CREATE TABLE task_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    field TEXT NOT NULL CHECK (field IN (
        'title', 'description', 'status_id', 'project_id',
        'priority', 'due_date', 'position', 'archived',
        'start_date', 'finish_date', 'group_id'
    )),
    old_value TEXT,
    new_value TEXT,
    source TEXT NOT NULL,
    changed_at INTEGER NOT NULL DEFAULT (unixepoch())
);
INSERT INTO task_history (id, task_id, field, old_value, new_value, source, changed_at)
SELECT id, task_id,
    CASE WHEN field = 'column_id' THEN 'status_id' ELSE field END,
    old_value, new_value, source, changed_at
FROM _task_history_old;
DROP TABLE _task_history_old;

-- Recreate task_dependencies (FK to tasks changed)
ALTER TABLE task_dependencies RENAME TO _task_dependencies_old;
CREATE TABLE task_dependencies (
    task_id INTEGER NOT NULL,
    depends_on_id INTEGER NOT NULL,
    board_id INTEGER NOT NULL,
    PRIMARY KEY (task_id, depends_on_id),
    CHECK (task_id != depends_on_id),
    FOREIGN KEY (task_id, board_id) REFERENCES tasks(id, board_id) ON DELETE CASCADE,
    FOREIGN KEY (depends_on_id, board_id) REFERENCES tasks(id, board_id) ON DELETE CASCADE
);
INSERT INTO task_dependencies (task_id, depends_on_id, board_id)
SELECT td.task_id, td.depends_on_id, t.board_id
FROM _task_dependencies_old td
JOIN tasks t ON t.id = td.task_id;
DROP TABLE _task_dependencies_old;

-- Recreate task_tags (FK to tasks changed)
ALTER TABLE task_tags RENAME TO _task_tags_old;
CREATE TABLE task_tags (
    task_id INTEGER NOT NULL,
    tag_id INTEGER NOT NULL,
    board_id INTEGER NOT NULL,
    PRIMARY KEY (task_id, tag_id),
    FOREIGN KEY (task_id, board_id) REFERENCES tasks(id, board_id) ON DELETE CASCADE,
    FOREIGN KEY (tag_id, board_id) REFERENCES tags(id, board_id) ON DELETE CASCADE
);
INSERT INTO task_tags (task_id, tag_id, board_id)
SELECT task_id, tag_id, board_id FROM _task_tags_old;
DROP TABLE _task_tags_old;

-- Indexes on statuses
CREATE UNIQUE INDEX uq_statuses_board_name_active
    ON statuses(board_id, name) WHERE archived = 0;
CREATE INDEX idx_statuses_board_archived_name
    ON statuses(board_id, archived, name, id);

-- Indexes on tasks (all task indexes were dropped with _tasks_old)
CREATE UNIQUE INDEX uq_tasks_board_title_active
    ON tasks(board_id, title) WHERE archived = 0;
CREATE INDEX idx_tasks_status_archived_position
    ON tasks(status_id, archived, position, id);
CREATE INDEX idx_tasks_board_archived_position
    ON tasks(board_id, archived, position, id);
CREATE INDEX idx_tasks_project_archived_position
    ON tasks(project_id, archived, position, id);
CREATE INDEX idx_tasks_project_archived_group
    ON tasks(project_id, archived, group_id);
CREATE INDEX idx_tasks_group_id ON tasks(group_id);

-- Indexes on task_history (dropped with _task_history_old)
CREATE INDEX idx_task_history_task_changed
    ON task_history(task_id, changed_at DESC, id DESC);

-- Indexes on task_dependencies (dropped with _task_dependencies_old)
CREATE INDEX idx_task_dependencies_depends_on_id
    ON task_dependencies(depends_on_id);

-- Indexes on task_tags (dropped with _task_tags_old)
CREATE INDEX idx_task_tags_tag_id ON task_tags(tag_id)
