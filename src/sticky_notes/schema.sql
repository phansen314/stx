CREATE TABLE IF NOT EXISTS workspaces (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL COLLATE NOCASE,
    archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)),
    created_at INTEGER NOT NULL DEFAULT (unixepoch())
);

CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id INTEGER NOT NULL REFERENCES workspaces(id) ON DELETE RESTRICT,
    name TEXT NOT NULL COLLATE NOCASE,
    description TEXT,
    archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)),
    created_at INTEGER NOT NULL DEFAULT (unixepoch()),
    UNIQUE (id, workspace_id)
);

CREATE TABLE IF NOT EXISTS statuses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id INTEGER NOT NULL REFERENCES workspaces(id) ON DELETE RESTRICT,
    name TEXT NOT NULL COLLATE NOCASE,
    archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)),
    created_at INTEGER NOT NULL DEFAULT (unixepoch()),
    UNIQUE (id, workspace_id)
);

CREATE TABLE IF NOT EXISTS groups (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE RESTRICT,
    parent_id  INTEGER,
    title      TEXT NOT NULL COLLATE NOCASE,
    position   INTEGER NOT NULL DEFAULT 0 CHECK (position >= 0),
    archived   INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)),
    created_at INTEGER NOT NULL DEFAULT (unixepoch()),
    UNIQUE (id, project_id),
    FOREIGN KEY (parent_id, project_id) REFERENCES groups(id, project_id) ON DELETE RESTRICT
);

CREATE TABLE IF NOT EXISTS tasks (
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
    CHECK (start_date IS NULL OR finish_date IS NULL OR finish_date >= start_date),
    CHECK (group_id IS NULL OR project_id IS NOT NULL),
    FOREIGN KEY (status_id, workspace_id) REFERENCES statuses(id, workspace_id) ON DELETE RESTRICT,
    FOREIGN KEY (project_id, workspace_id) REFERENCES projects(id, workspace_id) ON DELETE RESTRICT,
    FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE RESTRICT,
    FOREIGN KEY (group_id, project_id) REFERENCES groups(id, project_id) ON DELETE RESTRICT,
    UNIQUE (id, workspace_id)
);

CREATE TABLE IF NOT EXISTS task_dependencies (
    task_id INTEGER NOT NULL,
    depends_on_id INTEGER NOT NULL,
    workspace_id INTEGER NOT NULL,
    PRIMARY KEY (task_id, depends_on_id),
    CHECK (task_id != depends_on_id),
    FOREIGN KEY (task_id, workspace_id) REFERENCES tasks(id, workspace_id) ON DELETE CASCADE,
    FOREIGN KEY (depends_on_id, workspace_id) REFERENCES tasks(id, workspace_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS group_dependencies (
    group_id      INTEGER NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    depends_on_id INTEGER NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    workspace_id  INTEGER NOT NULL REFERENCES workspaces(id),
    PRIMARY KEY (group_id, depends_on_id),
    CHECK (group_id != depends_on_id)
);

CREATE TABLE IF NOT EXISTS tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id INTEGER NOT NULL REFERENCES workspaces(id) ON DELETE RESTRICT,
    name TEXT NOT NULL COLLATE NOCASE,
    archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)),
    created_at INTEGER NOT NULL DEFAULT (unixepoch()),
    UNIQUE (id, workspace_id)
);

CREATE TABLE IF NOT EXISTS task_tags (
    task_id INTEGER NOT NULL,
    tag_id INTEGER NOT NULL,
    workspace_id INTEGER NOT NULL,
    PRIMARY KEY (task_id, tag_id),
    FOREIGN KEY (task_id, workspace_id) REFERENCES tasks(id, workspace_id) ON DELETE CASCADE,
    FOREIGN KEY (tag_id, workspace_id) REFERENCES tags(id, workspace_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS task_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    field TEXT NOT NULL CHECK (field IN (__TASK_FIELD_VALUES__)),
    old_value TEXT,
    new_value TEXT,
    source TEXT NOT NULL,
    changed_at INTEGER NOT NULL DEFAULT (unixepoch())
);

-- Partial unique indexes: scoped to active (non-archived) rows only.
-- Archived rows do not block re-creation of entities with the same name/title.
CREATE UNIQUE INDEX IF NOT EXISTS uq_workspaces_name_active
    ON workspaces(name) WHERE archived = 0;
CREATE UNIQUE INDEX IF NOT EXISTS uq_projects_workspace_name_active
    ON projects(workspace_id, name) WHERE archived = 0;
CREATE UNIQUE INDEX IF NOT EXISTS uq_statuses_workspace_name_active
    ON statuses(workspace_id, name) WHERE archived = 0;
CREATE UNIQUE INDEX IF NOT EXISTS uq_tags_workspace_name_active
    ON tags(workspace_id, name) WHERE archived = 0;
CREATE UNIQUE INDEX IF NOT EXISTS uq_groups_project_title_active
    ON groups(project_id, title) WHERE archived = 0;
CREATE UNIQUE INDEX IF NOT EXISTS uq_tasks_workspace_title_active
    ON tasks(workspace_id, title) WHERE archived = 0;

-- Composite covering indexes aligned to actual query patterns
-- (each covers WHERE <fk> = ? AND archived = 0 ORDER BY <sort>)
CREATE INDEX IF NOT EXISTS idx_tasks_status_archived_position
    ON tasks(status_id, archived, position, id);
CREATE INDEX IF NOT EXISTS idx_tasks_workspace_archived_position
    ON tasks(workspace_id, archived, position, id);
CREATE INDEX IF NOT EXISTS idx_tasks_project_archived_position
    ON tasks(project_id, archived, position, id);
CREATE INDEX IF NOT EXISTS idx_statuses_workspace_archived_name
    ON statuses(workspace_id, archived, name, id);
CREATE INDEX IF NOT EXISTS idx_groups_parent_archived_position
    ON groups(parent_id, archived, position, id);
CREATE INDEX IF NOT EXISTS idx_groups_project_archived_position
    ON groups(project_id, archived, position, id);
CREATE INDEX IF NOT EXISTS idx_tags_workspace_archived_name
    ON tags(workspace_id, archived, name);
CREATE INDEX IF NOT EXISTS idx_task_history_task_changed
    ON task_history(task_id, changed_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_tasks_project_archived_group
    ON tasks(project_id, archived, group_id);

-- FK indexes on junction/audit tables (PK covers the leading column)
CREATE INDEX IF NOT EXISTS idx_task_dependencies_depends_on_id
    ON task_dependencies(depends_on_id);
CREATE INDEX IF NOT EXISTS idx_group_dependencies_depends_on_id
    ON group_dependencies(depends_on_id);
CREATE INDEX IF NOT EXISTS idx_task_tags_tag_id
    ON task_tags(tag_id);

-- FK index for tasks.group_id (not covered by composites above)
CREATE INDEX IF NOT EXISTS idx_tasks_group_id ON tasks(group_id);
