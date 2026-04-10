-- Add metadata columns to workspaces, projects, groups (parallel to the
-- existing tasks.metadata added in migration 010). Also retroactively tighten
-- tasks.metadata with CHECK (json_valid(metadata)), which migration 010
-- omitted. This requires recreating the tasks table and its FK-dependent
-- children (task_dependencies, task_tags, task_history).

-- ---- workspaces / projects / groups: simple ALTER TABLE ----

ALTER TABLE workspaces ADD COLUMN metadata TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata));
ALTER TABLE projects ADD COLUMN metadata TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata));
ALTER TABLE groups ADD COLUMN metadata TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata));

-- ---- tasks: recreate to add CHECK (json_valid(metadata)) ----
--
-- SQLite can't add a CHECK to an existing column in-place. Follow the same
-- cascade-recreate pattern used by migration 008: recreate tasks_new with the
-- new constraint, recreate task_dependencies / task_tags / task_history with
-- FKs pointing at tasks_new, then drop/rename. SQLite auto-redirects FK
-- references in the child tables when tasks_new is renamed to tasks.

CREATE TABLE tasks_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id INTEGER NOT NULL,
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
    metadata TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata)),
    CHECK (start_date IS NULL OR finish_date IS NULL OR finish_date >= start_date),
    CHECK (group_id IS NULL OR project_id IS NOT NULL),
    FOREIGN KEY (status_id, workspace_id) REFERENCES statuses(id, workspace_id) ON DELETE RESTRICT,
    FOREIGN KEY (project_id, workspace_id) REFERENCES projects(id, workspace_id) ON DELETE RESTRICT,
    FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE RESTRICT,
    FOREIGN KEY (group_id, project_id) REFERENCES groups(id, project_id) ON DELETE RESTRICT,
    UNIQUE (id, workspace_id)
);
INSERT INTO tasks_new (id, workspace_id, project_id, title, description, status_id, priority,
                       due_date, position, archived, created_at, start_date, finish_date, group_id, metadata)
    SELECT id, workspace_id, project_id, title, description, status_id, priority,
           due_date, position, archived, created_at, start_date, finish_date, group_id, metadata
    FROM tasks;

-- Cascade-recreate tables with FK refs to tasks
CREATE TABLE task_dependencies_new (
    task_id INTEGER NOT NULL,
    depends_on_id INTEGER NOT NULL,
    workspace_id INTEGER NOT NULL,
    archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)),
    PRIMARY KEY (task_id, depends_on_id),
    CHECK (task_id != depends_on_id),
    FOREIGN KEY (task_id, workspace_id) REFERENCES tasks_new(id, workspace_id) ON DELETE CASCADE,
    FOREIGN KEY (depends_on_id, workspace_id) REFERENCES tasks_new(id, workspace_id) ON DELETE CASCADE
);
INSERT INTO task_dependencies_new (task_id, depends_on_id, workspace_id, archived)
    SELECT task_id, depends_on_id, workspace_id, archived FROM task_dependencies;
DROP TABLE task_dependencies;
ALTER TABLE task_dependencies_new RENAME TO task_dependencies;
CREATE INDEX idx_task_dependencies_depends_on_id ON task_dependencies(depends_on_id);

CREATE TABLE task_tags_new (
    task_id INTEGER NOT NULL,
    tag_id INTEGER NOT NULL,
    workspace_id INTEGER NOT NULL,
    PRIMARY KEY (task_id, tag_id),
    FOREIGN KEY (task_id, workspace_id) REFERENCES tasks_new(id, workspace_id) ON DELETE CASCADE,
    FOREIGN KEY (tag_id, workspace_id) REFERENCES tags(id, workspace_id) ON DELETE CASCADE
);
INSERT INTO task_tags_new (task_id, tag_id, workspace_id)
    SELECT task_id, tag_id, workspace_id FROM task_tags;
DROP TABLE task_tags;
ALTER TABLE task_tags_new RENAME TO task_tags;
CREATE INDEX idx_task_tags_tag_id ON task_tags(tag_id);

-- task_history: recreate for FK to tasks_new. Since the recreate cost is
-- already sunk, also add the CHECK (field IN (...)) constraint that
-- schema.sql has on fresh DBs but migrated DBs lost in migration 008.
-- Values are hardcoded (not templated through read_schema) because migration
-- files are historical records of schema state at time-of-writing. A future
-- TaskField addition requires a new migration to extend the CHECK.
CREATE TABLE task_history_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL REFERENCES tasks_new(id) ON DELETE CASCADE,
    workspace_id INTEGER NOT NULL REFERENCES workspaces(id) ON DELETE RESTRICT,
    field TEXT NOT NULL CHECK (field IN (
        'title', 'description', 'status_id', 'project_id', 'priority',
        'due_date', 'position', 'archived', 'start_date', 'finish_date', 'group_id'
    )),
    old_value TEXT,
    new_value TEXT,
    source TEXT NOT NULL,
    changed_at INTEGER NOT NULL DEFAULT (unixepoch())
);
INSERT INTO task_history_new (id, task_id, workspace_id, field, old_value, new_value, source, changed_at)
    SELECT id, task_id, workspace_id, field, old_value, new_value, source, changed_at FROM task_history;
DROP TABLE task_history;
ALTER TABLE task_history_new RENAME TO task_history;
CREATE INDEX idx_task_history_task_changed ON task_history(task_id, changed_at DESC, id DESC);

DROP TABLE tasks;
ALTER TABLE tasks_new RENAME TO tasks;
CREATE UNIQUE INDEX uq_tasks_workspace_title_active ON tasks(workspace_id, title) WHERE archived = 0;
CREATE INDEX idx_tasks_status_archived_position ON tasks(status_id, archived, position, id);
CREATE INDEX idx_tasks_workspace_archived_position ON tasks(workspace_id, archived, position, id);
CREATE INDEX idx_tasks_project_archived_position ON tasks(project_id, archived, position, id);
CREATE INDEX idx_tasks_project_archived_group ON tasks(project_id, archived, group_id);
CREATE INDEX idx_tasks_group_id ON tasks(group_id);
