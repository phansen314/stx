CREATE TABLE IF NOT EXISTS workspaces (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL COLLATE NOCASE,
    archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)),
    created_at INTEGER NOT NULL DEFAULT (unixepoch()),
    metadata TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata))
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

CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id INTEGER NOT NULL,
    title TEXT NOT NULL COLLATE NOCASE,
    description TEXT,
    status_id INTEGER NOT NULL,
    priority INTEGER NOT NULL DEFAULT 1,
    due_date INTEGER,
    position INTEGER NOT NULL DEFAULT 0 CHECK (position >= 0),
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

CREATE TABLE IF NOT EXISTS edges (
    from_type    TEXT NOT NULL CHECK (from_type IN ('workspace', 'group', 'task')),
    from_id      INTEGER NOT NULL,
    to_type      TEXT NOT NULL CHECK (to_type IN ('workspace', 'group', 'task')),
    to_id        INTEGER NOT NULL,
    workspace_id INTEGER NOT NULL REFERENCES workspaces(id),
    -- kind charset kept tight so export.py can safely interpolate it into
    -- Mermaid edge labels (|kind|) without escaping. Loosening this must
    -- be paired with an escape pass in export._render_edges_section
    kind         TEXT NOT NULL DEFAULT 'blocks'
                     CHECK (kind GLOB '[a-z0-9_.-]*' AND length(kind) BETWEEN 1 AND 64),
    acyclic      INTEGER NOT NULL DEFAULT 0 CHECK (acyclic IN (0, 1)),
    metadata     TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata)),
    archived     INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)),
    PRIMARY KEY (from_type, from_id, to_type, to_id, kind),
    CHECK (from_type != to_type OR from_id != to_id)
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

CREATE TABLE IF NOT EXISTS journal (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type TEXT NOT NULL CHECK (entity_type IN (
        'task', 'group', 'workspace', 'status', 'edge'
    )),
    entity_id INTEGER NOT NULL,
    workspace_id INTEGER NOT NULL REFERENCES workspaces(id) ON DELETE RESTRICT,
    field TEXT NOT NULL,
    old_value TEXT,
    new_value TEXT,
    source TEXT NOT NULL,
    changed_at INTEGER NOT NULL DEFAULT (unixepoch())
);

-- Partial unique indexes: scoped to active (non-archived) rows only
CREATE UNIQUE INDEX IF NOT EXISTS uq_workspaces_name_active
    ON workspaces(name) WHERE archived = 0;
CREATE UNIQUE INDEX IF NOT EXISTS uq_statuses_workspace_name_active
    ON statuses(workspace_id, name) WHERE archived = 0;
CREATE UNIQUE INDEX IF NOT EXISTS uq_tags_workspace_name_active
    ON tags(workspace_id, name) WHERE archived = 0;
CREATE UNIQUE INDEX IF NOT EXISTS uq_groups_workspace_parent_title_active
    ON groups(workspace_id, COALESCE(parent_id, -1), title) WHERE archived = 0;
CREATE UNIQUE INDEX IF NOT EXISTS uq_tasks_workspace_title_active
    ON tasks(workspace_id, title) WHERE archived = 0;

-- Composite covering indexes aligned to actual query patterns
CREATE INDEX IF NOT EXISTS idx_tasks_status_archived_position
    ON tasks(status_id, archived, position, id);
CREATE INDEX IF NOT EXISTS idx_tasks_workspace_archived_position
    ON tasks(workspace_id, archived, position, id);
CREATE INDEX IF NOT EXISTS idx_statuses_workspace_archived_name
    ON statuses(workspace_id, archived, name, id);
CREATE INDEX IF NOT EXISTS idx_groups_parent_archived_position
    ON groups(parent_id, archived, position, id);
CREATE INDEX IF NOT EXISTS idx_groups_workspace_archived_position
    ON groups(workspace_id, archived, position, id);
CREATE INDEX IF NOT EXISTS idx_tags_workspace_archived_name
    ON tags(workspace_id, archived, name);
CREATE INDEX IF NOT EXISTS idx_journal_entity
    ON journal(entity_type, entity_id, changed_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_journal_timeline
    ON journal(workspace_id, changed_at DESC);
CREATE INDEX IF NOT EXISTS idx_tasks_workspace_archived_group
    ON tasks(workspace_id, archived, group_id);

-- Edges indexes: covering patterns for DAG queries and endpoint lookups
CREATE INDEX IF NOT EXISTS idx_edges_from
    ON edges(from_type, from_id);
CREATE INDEX IF NOT EXISTS idx_edges_to
    ON edges(to_type, to_id);
CREATE INDEX IF NOT EXISTS idx_edges_workspace_archived
    ON edges(workspace_id, archived);
CREATE INDEX IF NOT EXISTS idx_edges_acyclic_archived
    ON edges(acyclic, archived);

-- FK indexes on junction tables (PK covers the leading column)
CREATE INDEX IF NOT EXISTS idx_task_tags_tag_id
    ON task_tags(tag_id);

-- FK index for tasks.group_id (not covered by composites above)
CREATE INDEX IF NOT EXISTS idx_tasks_group_id ON tasks(group_id);
