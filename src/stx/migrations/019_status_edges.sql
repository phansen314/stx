-- Migration 019: allow 'status' as an edge endpoint node type.
--
-- Enables workspace-scoped state-machine enforcement: transition edges
-- between statuses (kind='transition'/'rollback'/'auto'/'skip') are stored
-- in the same polymorphic edges table. When transition edges exist out of
-- a status, update_task() enforces them; otherwise any->any moves remain
-- allowed for backwards compat.
--
-- Existing rows carry endpoint types IN ('workspace','group','task'), so
-- no data migration is needed — only the CHECK constraints widen. SQLite
-- cannot ALTER a CHECK, so cascade-recreate edges.

ALTER TABLE edges RENAME TO edges_old;

CREATE TABLE edges (
    from_type    TEXT NOT NULL CHECK (from_type IN ('workspace', 'group', 'task', 'status')),
    from_id      INTEGER NOT NULL,
    to_type      TEXT NOT NULL CHECK (to_type IN ('workspace', 'group', 'task', 'status')),
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

INSERT INTO edges (from_type, from_id, to_type, to_id, workspace_id, kind, acyclic, metadata, archived)
    SELECT from_type, from_id, to_type, to_id, workspace_id, kind, acyclic, metadata, archived
    FROM edges_old;

DROP TABLE edges_old;

CREATE INDEX idx_edges_from ON edges(from_type, from_id);
CREATE INDEX idx_edges_to ON edges(to_type, to_id);
CREATE INDEX idx_edges_workspace_archived ON edges(workspace_id, archived);
CREATE INDEX idx_edges_acyclic_archived ON edges(acyclic, archived);
