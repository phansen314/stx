-- Build project-to-root-group ID mapping using pre-existing max group ID
CREATE TEMPORARY TABLE _proj_group_map (
    project_id INTEGER NOT NULL,
    group_id   INTEGER NOT NULL
);

INSERT INTO _proj_group_map (project_id, group_id)
SELECT
    id,
    (SELECT COALESCE(MAX(id), 0) FROM groups) + ROW_NUMBER() OVER (ORDER BY id)
FROM projects;

-- Recreate groups without project_id
ALTER TABLE groups RENAME TO groups_old;

CREATE TABLE groups (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id INTEGER NOT NULL REFERENCES workspaces(id) ON DELETE RESTRICT,
    parent_id    INTEGER,
    title        TEXT NOT NULL COLLATE NOCASE,
    description  TEXT,
    position     INTEGER NOT NULL DEFAULT 0 CHECK (position >= 0),
    archived     INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)),
    created_at   INTEGER NOT NULL DEFAULT (unixepoch()),
    metadata     TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata)),
    UNIQUE (id, workspace_id),
    FOREIGN KEY (parent_id, workspace_id) REFERENCES groups(id, workspace_id) ON DELETE RESTRICT
);

INSERT INTO groups (id, workspace_id, parent_id, title, description, position, archived, created_at, metadata)
SELECT id, workspace_id, parent_id, title, description, position, archived, created_at, metadata
FROM groups_old;

INSERT INTO groups (id, workspace_id, parent_id, title, description, position, archived, created_at, metadata)
SELECT m.group_id, p.workspace_id, NULL, p.name, p.description, 0, p.archived, p.created_at, p.metadata
FROM projects p
JOIN _proj_group_map m ON m.project_id = p.id;

UPDATE groups
SET parent_id = (
    SELECT m.group_id
    FROM _proj_group_map m
    JOIN groups_old go ON go.id = groups.id
    WHERE m.project_id = go.project_id
)
WHERE id IN (SELECT id FROM groups_old WHERE parent_id IS NULL);

-- Cascade-recreate group_edges to point at new groups table
ALTER TABLE group_edges RENAME TO group_edges_old;

CREATE TABLE group_edges (
    source_id INTEGER NOT NULL,
    target_id INTEGER NOT NULL,
    workspace_id INTEGER NOT NULL,
    archived     INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)),
    kind         TEXT NOT NULL
        CHECK (kind GLOB '[a-z0-9_.-]*' AND length(kind) BETWEEN 1 AND 64),
    metadata     TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata)),
    PRIMARY KEY (source_id, target_id),
    CHECK (source_id != target_id),
    FOREIGN KEY (source_id, workspace_id) REFERENCES groups(id, workspace_id) ON DELETE CASCADE,
    FOREIGN KEY (target_id, workspace_id) REFERENCES groups(id, workspace_id) ON DELETE CASCADE
);

INSERT INTO group_edges SELECT * FROM group_edges_old;
DROP TABLE group_edges_old;
DROP TABLE groups_old;

ALTER TABLE tasks RENAME TO tasks_old;

CREATE TABLE tasks (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id INTEGER NOT NULL,
    title        TEXT NOT NULL COLLATE NOCASE,
    description  TEXT,
    status_id    INTEGER NOT NULL,
    priority     INTEGER NOT NULL DEFAULT 1,
    due_date     INTEGER,
    position     INTEGER NOT NULL DEFAULT 0 CHECK (position >= 0),
    archived     INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)),
    created_at   INTEGER NOT NULL DEFAULT (unixepoch()),
    start_date   INTEGER,
    finish_date  INTEGER,
    group_id     INTEGER,
    metadata     TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata)),
    CHECK (start_date IS NULL OR finish_date IS NULL OR finish_date >= start_date),
    FOREIGN KEY (status_id, workspace_id) REFERENCES statuses(id, workspace_id) ON DELETE RESTRICT,
    FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE RESTRICT,
    FOREIGN KEY (group_id, workspace_id) REFERENCES groups(id, workspace_id) ON DELETE RESTRICT,
    UNIQUE (id, workspace_id)
);

INSERT INTO tasks (id, workspace_id, title, description, status_id, priority, due_date, position, archived, created_at, start_date, finish_date, group_id, metadata)
SELECT
    t.id, t.workspace_id, t.title, t.description, t.status_id, t.priority,
    t.due_date, t.position, t.archived, t.created_at, t.start_date, t.finish_date,
    CASE
        WHEN t.group_id IS NOT NULL THEN t.group_id
        WHEN t.project_id IS NOT NULL THEN (SELECT m.group_id FROM _proj_group_map m WHERE m.project_id = t.project_id)
        ELSE NULL
    END,
    t.metadata
FROM tasks_old t;

-- Cascade-recreate task_edges and task_tags to point at new tasks table
ALTER TABLE task_edges RENAME TO task_edges_old;

CREATE TABLE task_edges (
    source_id INTEGER NOT NULL,
    target_id INTEGER NOT NULL,
    workspace_id INTEGER NOT NULL,
    archived     INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)),
    kind         TEXT NOT NULL
        CHECK (kind GLOB '[a-z0-9_.-]*' AND length(kind) BETWEEN 1 AND 64),
    metadata     TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata)),
    PRIMARY KEY (source_id, target_id),
    CHECK (source_id != target_id),
    FOREIGN KEY (source_id, workspace_id) REFERENCES tasks(id, workspace_id) ON DELETE CASCADE,
    FOREIGN KEY (target_id, workspace_id) REFERENCES tasks(id, workspace_id) ON DELETE CASCADE
);

INSERT INTO task_edges SELECT * FROM task_edges_old;
DROP TABLE task_edges_old;

ALTER TABLE task_tags RENAME TO task_tags_old;

CREATE TABLE task_tags (
    task_id      INTEGER NOT NULL,
    tag_id       INTEGER NOT NULL,
    workspace_id INTEGER NOT NULL,
    PRIMARY KEY (task_id, tag_id),
    FOREIGN KEY (task_id, workspace_id) REFERENCES tasks(id, workspace_id) ON DELETE CASCADE,
    FOREIGN KEY (tag_id, workspace_id) REFERENCES tags(id, workspace_id) ON DELETE CASCADE
);

INSERT INTO task_tags SELECT * FROM task_tags_old;
DROP TABLE task_tags_old;
DROP TABLE tasks_old;

ALTER TABLE journal RENAME TO journal_old;

CREATE TABLE journal (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type  TEXT NOT NULL CHECK (entity_type IN (
        'task', 'group', 'workspace', 'status',
        'task_edge', 'group_edge'
    )),
    entity_id    INTEGER NOT NULL,
    workspace_id INTEGER NOT NULL REFERENCES workspaces(id) ON DELETE RESTRICT,
    field        TEXT NOT NULL,
    old_value    TEXT,
    new_value    TEXT,
    source       TEXT NOT NULL,
    changed_at   INTEGER NOT NULL DEFAULT (unixepoch())
);

INSERT INTO journal (id, entity_type, entity_id, workspace_id, field, old_value, new_value, source, changed_at)
SELECT id, entity_type, entity_id, workspace_id, field, old_value, new_value, source, changed_at
FROM journal_old
WHERE entity_type != 'project';

DROP TABLE journal_old;
DROP TABLE projects;
DROP TABLE IF EXISTS _proj_group_map;

CREATE UNIQUE INDEX IF NOT EXISTS uq_tasks_workspace_title_active
    ON tasks(workspace_id, title) WHERE archived = 0;
CREATE INDEX IF NOT EXISTS idx_tasks_status_archived_position
    ON tasks(status_id, archived, position, id);
CREATE INDEX IF NOT EXISTS idx_tasks_workspace_archived_position
    ON tasks(workspace_id, archived, position, id);
CREATE INDEX IF NOT EXISTS idx_tasks_group_id ON tasks(group_id);
CREATE INDEX IF NOT EXISTS idx_tasks_workspace_archived_group
    ON tasks(workspace_id, archived, group_id);

CREATE UNIQUE INDEX IF NOT EXISTS uq_groups_workspace_parent_title_active
    ON groups(workspace_id, COALESCE(parent_id, -1), title) WHERE archived = 0;
CREATE INDEX IF NOT EXISTS idx_groups_parent_archived_position
    ON groups(parent_id, archived, position, id);
CREATE INDEX IF NOT EXISTS idx_groups_workspace_archived_position
    ON groups(workspace_id, archived, position, id);

CREATE INDEX IF NOT EXISTS idx_task_edges_target_id ON task_edges(target_id);
CREATE INDEX IF NOT EXISTS idx_task_tags_tag_id ON task_tags(tag_id);

CREATE INDEX IF NOT EXISTS idx_group_edges_target_id ON group_edges(target_id);

CREATE INDEX IF NOT EXISTS idx_journal_entity
    ON journal(entity_type, entity_id, changed_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_journal_timeline
    ON journal(workspace_id, changed_at DESC)
