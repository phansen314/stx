-- Rename boards table to workspaces
DROP INDEX IF EXISTS uq_boards_name_active;
ALTER TABLE boards RENAME TO workspaces;
CREATE UNIQUE INDEX uq_workspaces_name_active
    ON workspaces(name) WHERE archived = 0;

-- Recreate projects: board_id -> workspace_id
ALTER TABLE projects RENAME TO _projects_old;
CREATE TABLE projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id INTEGER NOT NULL REFERENCES workspaces(id) ON DELETE RESTRICT,
    name TEXT NOT NULL COLLATE NOCASE,
    description TEXT,
    archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)),
    created_at INTEGER NOT NULL DEFAULT (unixepoch()),
    UNIQUE (id, workspace_id)
);
INSERT INTO projects (id, workspace_id, name, description, archived, created_at)
SELECT id, board_id, name, description, archived, created_at FROM _projects_old;
DROP TABLE _projects_old;

-- Recreate statuses: board_id -> workspace_id
ALTER TABLE statuses RENAME TO _statuses_old;
CREATE TABLE statuses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id INTEGER NOT NULL REFERENCES workspaces(id) ON DELETE RESTRICT,
    name TEXT NOT NULL COLLATE NOCASE,
    archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)),
    created_at INTEGER NOT NULL DEFAULT (unixepoch()),
    UNIQUE (id, workspace_id)
);
INSERT INTO statuses (id, workspace_id, name, archived, created_at)
SELECT id, board_id, name, archived, created_at FROM _statuses_old;
DROP TABLE _statuses_old;

-- Recreate tasks: board_id -> workspace_id, update composite FKs
ALTER TABLE tasks RENAME TO _tasks_old;
CREATE TABLE tasks (
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
INSERT INTO tasks
(id, workspace_id, project_id, title, description, status_id, priority,
 due_date, position, archived, created_at, start_date, finish_date, group_id)
SELECT id, board_id, project_id, title, description, status_id, priority,
       due_date, position, archived, created_at, start_date, finish_date, group_id
FROM _tasks_old;
DROP TABLE _tasks_old;

-- Recreate tags: board_id -> workspace_id
ALTER TABLE tags RENAME TO _tags_old;
CREATE TABLE tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id INTEGER NOT NULL REFERENCES workspaces(id) ON DELETE RESTRICT,
    name TEXT NOT NULL COLLATE NOCASE,
    archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)),
    created_at INTEGER NOT NULL DEFAULT (unixepoch()),
    UNIQUE (id, workspace_id)
);
INSERT INTO tags (id, workspace_id, name, archived, created_at)
SELECT id, board_id, name, archived, created_at FROM _tags_old;
DROP TABLE _tags_old;

-- Recreate group_dependencies: board_id -> workspace_id
ALTER TABLE group_dependencies RENAME TO _group_dependencies_old;
CREATE TABLE group_dependencies (
    group_id      INTEGER NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    depends_on_id INTEGER NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    workspace_id  INTEGER NOT NULL REFERENCES workspaces(id),
    PRIMARY KEY (group_id, depends_on_id),
    CHECK (group_id != depends_on_id)
);
INSERT INTO group_dependencies (group_id, depends_on_id, workspace_id)
SELECT group_id, depends_on_id, board_id FROM _group_dependencies_old;
DROP TABLE _group_dependencies_old;

-- Recreate task_dependencies: board_id -> workspace_id
ALTER TABLE task_dependencies RENAME TO _task_dependencies_old;
CREATE TABLE task_dependencies (
    task_id INTEGER NOT NULL,
    depends_on_id INTEGER NOT NULL,
    workspace_id INTEGER NOT NULL,
    PRIMARY KEY (task_id, depends_on_id),
    CHECK (task_id != depends_on_id),
    FOREIGN KEY (task_id, workspace_id) REFERENCES tasks(id, workspace_id) ON DELETE CASCADE,
    FOREIGN KEY (depends_on_id, workspace_id) REFERENCES tasks(id, workspace_id) ON DELETE CASCADE
);
INSERT INTO task_dependencies (task_id, depends_on_id, workspace_id)
SELECT task_id, depends_on_id, board_id FROM _task_dependencies_old;
DROP TABLE _task_dependencies_old;

-- Recreate task_tags: board_id -> workspace_id
ALTER TABLE task_tags RENAME TO _task_tags_old;
CREATE TABLE task_tags (
    task_id INTEGER NOT NULL,
    tag_id INTEGER NOT NULL,
    workspace_id INTEGER NOT NULL,
    PRIMARY KEY (task_id, tag_id),
    FOREIGN KEY (task_id, workspace_id) REFERENCES tasks(id, workspace_id) ON DELETE CASCADE,
    FOREIGN KEY (tag_id, workspace_id) REFERENCES tags(id, workspace_id) ON DELETE CASCADE
);
INSERT INTO task_tags (task_id, tag_id, workspace_id)
SELECT task_id, tag_id, board_id FROM _task_tags_old;
DROP TABLE _task_tags_old;

-- Indexes for projects
CREATE UNIQUE INDEX uq_projects_workspace_name_active
    ON projects(workspace_id, name) WHERE archived = 0;

-- Indexes for statuses (dropped with _statuses_old)
CREATE UNIQUE INDEX uq_statuses_workspace_name_active
    ON statuses(workspace_id, name) WHERE archived = 0;
CREATE INDEX idx_statuses_workspace_archived_name
    ON statuses(workspace_id, archived, name, id);

-- Indexes for tasks (dropped with _tasks_old)
CREATE UNIQUE INDEX uq_tasks_workspace_title_active
    ON tasks(workspace_id, title) WHERE archived = 0;
CREATE INDEX idx_tasks_status_archived_position
    ON tasks(status_id, archived, position, id);
CREATE INDEX idx_tasks_workspace_archived_position
    ON tasks(workspace_id, archived, position, id);
CREATE INDEX idx_tasks_project_archived_position
    ON tasks(project_id, archived, position, id);
CREATE INDEX idx_tasks_project_archived_group
    ON tasks(project_id, archived, group_id);
CREATE INDEX idx_tasks_group_id ON tasks(group_id);

-- Indexes for tags (dropped with _tags_old)
CREATE UNIQUE INDEX uq_tags_workspace_name_active
    ON tags(workspace_id, name) WHERE archived = 0;
CREATE INDEX idx_tags_workspace_archived_name
    ON tags(workspace_id, archived, name);

-- Indexes for task_dependencies (dropped with _task_dependencies_old)
CREATE INDEX idx_task_dependencies_depends_on_id
    ON task_dependencies(depends_on_id);

-- Indexes for group_dependencies (dropped with _group_dependencies_old)
CREATE INDEX idx_group_dependencies_depends_on_id
    ON group_dependencies(depends_on_id);

-- Indexes for task_tags (dropped with _task_tags_old)
CREATE INDEX idx_task_tags_tag_id ON task_tags(tag_id)
