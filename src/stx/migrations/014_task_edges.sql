-- Rename task_dependencies → task_edges, group_dependencies → group_edges.
-- Add `kind TEXT NOT NULL` (with GLOB CHECK) and `metadata` JSON blob to both tables.
-- Backfill existing rows with kind='blocks' (old deps were blocking by definition).
-- Recreate `groups` to add UNIQUE (id, workspace_id) so `group_edges` can use a
-- workspace-scoped composite FK (mirrors how task_edges anchors to tasks).
-- Also recreate journal table to update entity_type CHECK constraint.
-- Column renames: task_id → source_id, depends_on_id → target_id for both tables.

-- 1. task_edges
CREATE TABLE task_edges (
    source_id INTEGER NOT NULL,
    target_id INTEGER NOT NULL,
    workspace_id INTEGER NOT NULL,
    archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)),
    kind TEXT NOT NULL
        CHECK (kind GLOB '[a-z0-9_.-]*' AND length(kind) BETWEEN 1 AND 64),
    metadata TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata)),
    PRIMARY KEY (source_id, target_id),
    CHECK (source_id != target_id),
    FOREIGN KEY (source_id, workspace_id) REFERENCES tasks(id, workspace_id) ON DELETE CASCADE,
    FOREIGN KEY (target_id, workspace_id) REFERENCES tasks(id, workspace_id) ON DELETE CASCADE
);
INSERT INTO task_edges (source_id, target_id, workspace_id, archived, kind)
    SELECT task_id, depends_on_id, workspace_id, archived, 'blocks' FROM task_dependencies;
DROP TABLE task_dependencies;

-- 2. groups — add UNIQUE (id, workspace_id) so group_edges can reference it
--    via a composite FK. Cascade-recreate. FK-off is already set by the
--    migration runner, so dependents (tasks.group_id, groups.parent_id) stay
--    consistent because we preserve the (id, project_id) tuple.
CREATE TABLE groups_new (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id INTEGER NOT NULL REFERENCES workspaces(id) ON DELETE RESTRICT,
    project_id   INTEGER NOT NULL REFERENCES projects(id) ON DELETE RESTRICT,
    parent_id    INTEGER,
    title        TEXT NOT NULL COLLATE NOCASE,
    description  TEXT,
    position     INTEGER NOT NULL DEFAULT 0 CHECK (position >= 0),
    archived     INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)),
    created_at   INTEGER NOT NULL DEFAULT (unixepoch()),
    metadata     TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata)),
    UNIQUE (id, project_id),
    UNIQUE (id, workspace_id),
    FOREIGN KEY (parent_id, project_id) REFERENCES groups_new(id, project_id) ON DELETE RESTRICT
);
INSERT INTO groups_new (
        id, workspace_id, project_id, parent_id, title, description,
        position, archived, created_at, metadata)
    SELECT id, workspace_id, project_id, parent_id, title, description,
           position, archived, created_at, metadata FROM groups;
DROP TABLE groups;
ALTER TABLE groups_new RENAME TO groups;
CREATE UNIQUE INDEX uq_groups_project_title_active
    ON groups(project_id, title) WHERE archived = 0;
CREATE INDEX idx_groups_parent_archived_position
    ON groups(parent_id, archived, position, id);
CREATE INDEX idx_groups_project_archived_position
    ON groups(project_id, archived, position, id);

-- 3. group_edges
CREATE TABLE group_edges (
    source_id INTEGER NOT NULL,
    target_id INTEGER NOT NULL,
    workspace_id INTEGER NOT NULL,
    archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)),
    kind TEXT NOT NULL
        CHECK (kind GLOB '[a-z0-9_.-]*' AND length(kind) BETWEEN 1 AND 64),
    metadata TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata)),
    PRIMARY KEY (source_id, target_id),
    CHECK (source_id != target_id),
    FOREIGN KEY (source_id, workspace_id) REFERENCES groups(id, workspace_id) ON DELETE CASCADE,
    FOREIGN KEY (target_id, workspace_id) REFERENCES groups(id, workspace_id) ON DELETE CASCADE
);
INSERT INTO group_edges (source_id, target_id, workspace_id, archived, kind)
    SELECT group_id, depends_on_id, workspace_id, archived, 'blocks' FROM group_dependencies;
DROP TABLE group_dependencies;

-- 3. Indexes
CREATE INDEX idx_task_edges_target_id ON task_edges(target_id);
CREATE INDEX idx_group_edges_target_id ON group_edges(target_id);

-- 4. Recreate journal with updated entity_type CHECK.
--    Use CASE in INSERT SELECT to rename entity_type values inline —
--    we cannot UPDATE the old table because its CHECK constraint blocks new values.
CREATE TABLE journal_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type TEXT NOT NULL CHECK (entity_type IN (
        'task', 'project', 'group', 'workspace', 'status',
        'task_edge', 'group_edge'
    )),
    entity_id INTEGER NOT NULL,
    workspace_id INTEGER NOT NULL REFERENCES workspaces(id) ON DELETE RESTRICT,
    field TEXT NOT NULL,
    old_value TEXT,
    new_value TEXT,
    source TEXT NOT NULL,
    changed_at INTEGER NOT NULL DEFAULT (unixepoch())
);
INSERT INTO journal_new (id, entity_type, entity_id, workspace_id, field, old_value, new_value, source, changed_at)
    SELECT
        id,
        CASE entity_type
            WHEN 'task_dependency' THEN 'task_edge'
            WHEN 'group_dependency' THEN 'group_edge'
            ELSE entity_type
        END,
        entity_id, workspace_id, field, old_value, new_value, source, changed_at
    FROM journal;
DROP TABLE journal;
ALTER TABLE journal_new RENAME TO journal;
CREATE INDEX idx_journal_entity
    ON journal(entity_type, entity_id, changed_at DESC, id DESC);
CREATE INDEX idx_journal_timeline
    ON journal(workspace_id, changed_at DESC);
