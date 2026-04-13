-- Migration 016: unify task_edges + group_edges into a single polymorphic
-- edges table. Adds acyclic flag for per-edge DAG-enforcement control.
-- Drops the two separate edge tables — all existing edges migrate with
-- acyclic=1 (they were dependency edges, which imply DAG semantics).
-- Also cascade-recreates the journal table to update its entity_type
-- CHECK constraint from ('task_edge','group_edge') to ('edge'), and
-- rewrites existing task_edge/group_edge journal rows.

-- 1. Create the new unified edges table
CREATE TABLE edges (
    from_type    TEXT NOT NULL CHECK (from_type IN ('workspace', 'group', 'task')),
    from_id      INTEGER NOT NULL,
    to_type      TEXT NOT NULL CHECK (to_type IN ('workspace', 'group', 'task')),
    to_id        INTEGER NOT NULL,
    workspace_id INTEGER NOT NULL REFERENCES workspaces(id),
    kind         TEXT NOT NULL DEFAULT 'blocks'
                     CHECK (kind GLOB '[a-z0-9_.-]*' AND length(kind) BETWEEN 1 AND 64),
    acyclic      INTEGER NOT NULL DEFAULT 0 CHECK (acyclic IN (0, 1)),
    metadata     TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata)),
    archived     INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1)),
    PRIMARY KEY (from_type, from_id, to_type, to_id, kind),
    CHECK (from_type != to_type OR from_id != to_id)
);

-- 2. Copy task_edges → edges (task→task, acyclic=1)
INSERT INTO edges (from_type, from_id, to_type, to_id, workspace_id, kind, acyclic, metadata, archived)
    SELECT 'task', source_id, 'task', target_id, workspace_id, kind, 1, metadata, archived
    FROM task_edges;

-- 3. Copy group_edges → edges (group→group, acyclic=1)
--    Plain INSERT: the PK includes from_type so task rows (step 2) and
--    group rows cannot collide.
INSERT INTO edges (from_type, from_id, to_type, to_id, workspace_id, kind, acyclic, metadata, archived)
    SELECT 'group', source_id, 'group', target_id, workspace_id, kind, 1, metadata, archived
    FROM group_edges;

-- 4. Drop old tables
DROP TABLE task_edges;
DROP TABLE group_edges;

-- 5. Add indexes for the new table
CREATE INDEX idx_edges_from ON edges(from_type, from_id);
CREATE INDEX idx_edges_to ON edges(to_type, to_id);
CREATE INDEX idx_edges_workspace_archived ON edges(workspace_id, archived);
CREATE INDEX idx_edges_acyclic_archived ON edges(acyclic, archived);

-- 6. Cascade-recreate journal to update entity_type CHECK constraint.
--    Old rows with entity_type IN ('task_edge','group_edge') are rewritten to 'edge'.
CREATE TABLE journal_new (
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

INSERT INTO journal_new (id, entity_type, entity_id, workspace_id, field, old_value, new_value, source, changed_at)
    SELECT
        id,
        CASE
            WHEN entity_type IN ('task_edge', 'group_edge') THEN 'edge'
            ELSE entity_type
        END,
        entity_id,
        workspace_id,
        field,
        old_value,
        new_value,
        source,
        changed_at
    FROM journal;

DROP TABLE journal;
ALTER TABLE journal_new RENAME TO journal;
CREATE INDEX idx_journal_entity
    ON journal(entity_type, entity_id, changed_at DESC, id DESC);
CREATE INDEX idx_journal_timeline
    ON journal(workspace_id, changed_at DESC);
