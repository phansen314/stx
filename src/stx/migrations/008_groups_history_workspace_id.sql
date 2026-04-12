-- Add workspace_id to groups and task_history so every table carries workspace_id.

-- ---- groups ----

CREATE TABLE groups_new (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id INTEGER NOT NULL REFERENCES workspaces(id) ON DELETE RESTRICT,
    project_id   INTEGER NOT NULL REFERENCES projects(id) ON DELETE RESTRICT,
    parent_id    INTEGER,
    title        TEXT NOT NULL COLLATE NOCASE,
    position     INTEGER NOT NULL DEFAULT 0 CHECK (position >= 0),
    archived     INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)),
    created_at   INTEGER NOT NULL DEFAULT (unixepoch()),
    UNIQUE (id, project_id),
    FOREIGN KEY (parent_id, project_id) REFERENCES groups_new(id, project_id) ON DELETE RESTRICT
);
INSERT INTO groups_new (id, workspace_id, project_id, parent_id, title, position, archived, created_at)
    SELECT g.id, p.workspace_id, g.project_id, g.parent_id, g.title, g.position, g.archived, g.created_at
    FROM groups g
    JOIN projects p ON g.project_id = p.id;

-- Cascade-recreate tables with FK refs to groups
CREATE TABLE group_dependencies_new (
    group_id      INTEGER NOT NULL REFERENCES groups_new(id) ON DELETE CASCADE,
    depends_on_id INTEGER NOT NULL REFERENCES groups_new(id) ON DELETE CASCADE,
    workspace_id  INTEGER NOT NULL REFERENCES workspaces(id),
    archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)),
    PRIMARY KEY (group_id, depends_on_id),
    CHECK (group_id != depends_on_id)
);
INSERT INTO group_dependencies_new (group_id, depends_on_id, workspace_id, archived)
    SELECT group_id, depends_on_id, workspace_id, archived FROM group_dependencies;
DROP TABLE group_dependencies;
ALTER TABLE group_dependencies_new RENAME TO group_dependencies;
CREATE INDEX idx_group_dependencies_depends_on_id ON group_dependencies(depends_on_id);

DROP TABLE groups;
ALTER TABLE groups_new RENAME TO groups;
CREATE UNIQUE INDEX uq_groups_project_title_active ON groups(project_id, title) WHERE archived = 0;
CREATE INDEX idx_groups_parent_archived_position ON groups(parent_id, archived, position, id);
CREATE INDEX idx_groups_project_archived_position ON groups(project_id, archived, position, id);

-- tasks has FK (group_id, project_id) -> groups(id, project_id) — must recreate
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
    CHECK (start_date IS NULL OR finish_date IS NULL OR finish_date >= start_date),
    CHECK (group_id IS NULL OR project_id IS NOT NULL),
    FOREIGN KEY (status_id, workspace_id) REFERENCES statuses(id, workspace_id) ON DELETE RESTRICT,
    FOREIGN KEY (project_id, workspace_id) REFERENCES projects(id, workspace_id) ON DELETE RESTRICT,
    FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE RESTRICT,
    FOREIGN KEY (group_id, project_id) REFERENCES groups(id, project_id) ON DELETE RESTRICT,
    UNIQUE (id, workspace_id)
);
INSERT INTO tasks_new (id, workspace_id, project_id, title, description, status_id, priority,
                       due_date, position, archived, created_at, start_date, finish_date, group_id)
    SELECT id, workspace_id, project_id, title, description, status_id, priority,
           due_date, position, archived, created_at, start_date, finish_date, group_id
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

-- task_history: add workspace_id AND recreate for FK to tasks_new
CREATE TABLE task_history_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL REFERENCES tasks_new(id) ON DELETE CASCADE,
    workspace_id INTEGER NOT NULL REFERENCES workspaces(id) ON DELETE RESTRICT,
    field TEXT NOT NULL,
    old_value TEXT,
    new_value TEXT,
    source TEXT NOT NULL,
    changed_at INTEGER NOT NULL DEFAULT (unixepoch())
);
INSERT INTO task_history_new (id, task_id, workspace_id, field, old_value, new_value, source, changed_at)
    SELECT h.id, h.task_id, t.workspace_id, h.field, h.old_value, h.new_value, h.source, h.changed_at
    FROM task_history h
    JOIN tasks t ON h.task_id = t.id;
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
