-- Migration 018: drop vestigial position column from tasks and groups.
--
-- The field was always defaulted to 0 and had no maintenance hooks: no TUI
-- drag/shift-reorder, no auto-reindex on status moves or group assignment,
-- and the cross-workspace transfer reset it anyway. Ordering reduces to
-- insertion order id ASC, so the column and its four covering indexes
-- carry no signal. Rip them out.
--
-- Groups are recreated before tasks so the tasks.group_id FK resolves
-- against the new groups table. Journal and edges tables do not FK into
-- tasks or groups in the modern schema, so no cascade-recreate is needed.
-- Historical journal rows with field = 'position' are left intact
-- (journal.field is unconstrained TEXT).

-- 1. Recreate groups without position
ALTER TABLE groups RENAME TO groups_old;

CREATE TABLE groups (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id INTEGER NOT NULL REFERENCES workspaces(id) ON DELETE RESTRICT,
    parent_id    INTEGER,
    title        TEXT NOT NULL COLLATE NOCASE,
    description  TEXT,
    archived     INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)),
    created_at   INTEGER NOT NULL DEFAULT (unixepoch()),
    metadata     TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata)),
    UNIQUE (id, workspace_id),
    FOREIGN KEY (parent_id, workspace_id) REFERENCES groups(id, workspace_id) ON DELETE RESTRICT
);

INSERT INTO groups (id, workspace_id, parent_id, title, description, archived, created_at, metadata)
SELECT id, workspace_id, parent_id, title, description, archived, created_at, metadata
FROM groups_old;

DROP TABLE groups_old;

-- 2. Recreate tasks without position
ALTER TABLE tasks RENAME TO tasks_old;

CREATE TABLE tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id INTEGER NOT NULL,
    title TEXT NOT NULL COLLATE NOCASE,
    description TEXT,
    status_id INTEGER NOT NULL,
    priority INTEGER NOT NULL DEFAULT 1,
    due_date INTEGER,
    archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)),
    created_at INTEGER NOT NULL DEFAULT (unixepoch()),
    start_date INTEGER,
    finish_date INTEGER,
    group_id INTEGER,
    metadata TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata)),
    CHECK (start_date IS NULL OR finish_date IS NULL OR finish_date >= start_date),
    FOREIGN KEY (status_id, workspace_id) REFERENCES statuses(id, workspace_id) ON DELETE RESTRICT,
    FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE RESTRICT,
    FOREIGN KEY (group_id, workspace_id) REFERENCES groups(id, workspace_id) ON DELETE RESTRICT,
    UNIQUE (id, workspace_id)
);

INSERT INTO tasks (id, workspace_id, title, description, status_id, priority, due_date, archived, created_at, start_date, finish_date, group_id, metadata)
SELECT id, workspace_id, title, description, status_id, priority, due_date, archived, created_at, start_date, finish_date, group_id, metadata
FROM tasks_old;

DROP TABLE tasks_old;

-- 3. Recreate indexes (old ones were dropped with the old tables)
CREATE UNIQUE INDEX uq_groups_workspace_parent_title_active
    ON groups(workspace_id, COALESCE(parent_id, -1), title) WHERE archived = 0;
CREATE INDEX idx_groups_parent_archived
    ON groups(parent_id, archived, id);
CREATE INDEX idx_groups_workspace_archived
    ON groups(workspace_id, archived, id);

CREATE UNIQUE INDEX uq_tasks_workspace_title_active
    ON tasks(workspace_id, title) WHERE archived = 0;
CREATE INDEX idx_tasks_status_archived
    ON tasks(status_id, archived, id);
CREATE INDEX idx_tasks_workspace_archived
    ON tasks(workspace_id, archived, id);
CREATE INDEX idx_tasks_workspace_archived_group
    ON tasks(workspace_id, archived, group_id);
CREATE INDEX idx_tasks_group_id ON tasks(group_id);
