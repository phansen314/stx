-- stx v3.0.0 — clean schema (greenfield, no migration)
--
-- Hierarchy:  workspace -> track -> segment* -> task
--   * workspace : top-level environment / edge boundary; holds many tracks.
--   * track     : ROOT-ONLY anchor (never nests, no parent). One coherent line of
--                 work. Carries track-level context (description + metadata).
--   * segment   : nestable filing node under a track. PURE FILING — no metadata,
--                 no context, no inheritance. parent is a segment or NULL (track root).
--   * task      : the only first-class node. Always attaches to exactly one segment
--                 (uniform parentage). "Add to the track" routes to its root segment.
--
-- Edges:
--   * blocks    : the spine. task -> task, acyclic. Drives `next`/frontier.
--   * relates_to: decorative association. task <-> task. Never affects `next`.
--
-- Design stance:
--   * Archive-only: nothing hard-deleted; `archived` hides rows; FKs never cascade.
--   * Integer autoincrement PKs.
--   * Balanced enforcement: structural FKs + cheap CHECKs in DB; graph invariants
--     (blocks-DAG acyclicity, segment-tree acyclicity, root-segment creation,
--     archive-cascade of edges, immutable segment.track_id) live in the daemon.
--   * No journal table; history is a non-authoritative sidecar log outside SQLite.

PRAGMA foreign_keys = ON;

-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE workspace (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT    NOT NULL,
    metadata_json TEXT    NOT NULL DEFAULT '{}',
    archived      INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- ─────────────────────────────────────────────────────────────────────────────
-- Status: lifecycle stage. The kanban columns ARE statuses.
CREATE TABLE status (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id INTEGER NOT NULL REFERENCES workspace(id) ON DELETE RESTRICT,
    name         TEXT    NOT NULL,
    kanban_order INTEGER NOT NULL DEFAULT 0,        -- display order only
    terminal     INTEGER NOT NULL DEFAULT 0,        -- terminal == "done"
    archived     INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE UNIQUE INDEX ux_status_ws_name_live
    ON status(workspace_id, name) WHERE archived = 0;

-- ─────────────────────────────────────────────────────────────────────────────
-- Status transitions: per-workspace state machine. Cycles allowed. No guards.
CREATE TABLE status_transition (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id   INTEGER NOT NULL REFERENCES workspace(id) ON DELETE RESTRICT,
    from_status_id INTEGER NOT NULL REFERENCES status(id)    ON DELETE RESTRICT,
    to_status_id   INTEGER NOT NULL REFERENCES status(id)    ON DELETE RESTRICT,
    archived       INTEGER NOT NULL DEFAULT 0,
    CHECK (from_status_id <> to_status_id)
);
CREATE UNIQUE INDEX ux_transition_live
    ON status_transition(workspace_id, from_status_id, to_status_id)
    WHERE archived = 0;

-- ─────────────────────────────────────────────────────────────────────────────
-- Track: ROOT-ONLY anchor. Never nests. Carries track-level context.
CREATE TABLE track (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id  INTEGER NOT NULL REFERENCES workspace(id) ON DELETE RESTRICT,
    name          TEXT    NOT NULL,
    description   TEXT    NOT NULL DEFAULT '',       -- the track blurb
    metadata_json TEXT    NOT NULL DEFAULT '{}',     -- e.g. jira_key, deadline
    archived      INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT    NOT NULL DEFAULT (datetime('now'))
    -- No parent: tracks exist only at the root level.
);

-- ─────────────────────────────────────────────────────────────────────────────
-- Segment: nestable filing node under a track. PURE FILING (no metadata/context).
--   * track_id          : denormalized root anchor (immutable) -> flat track-scope queries.
--   * parent_segment_id : the tree; NULL means "directly under the track" (root).
--   * is_root           : the synthetic root segment auto-created with each track;
--                         tasks added "to the track" land here. One per track (daemon).
CREATE TABLE segment (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id      INTEGER NOT NULL REFERENCES workspace(id) ON DELETE RESTRICT,
    track_id          INTEGER NOT NULL REFERENCES track(id)     ON DELETE RESTRICT,
    parent_segment_id INTEGER          REFERENCES segment(id)   ON DELETE RESTRICT,
    name              TEXT    NOT NULL,
    is_root           INTEGER NOT NULL DEFAULT 0,
    archived          INTEGER NOT NULL DEFAULT 0,
    created_at        TEXT    NOT NULL DEFAULT (datetime('now')),
    CHECK (parent_segment_id IS NULL OR parent_segment_id <> id)   -- no self-parent
    -- A root segment has parent_segment_id IS NULL. Deeper cycle prevention: daemon.
);
CREATE INDEX ix_segment_track  ON segment(track_id)          WHERE archived = 0;
CREATE INDEX ix_segment_parent ON segment(parent_segment_id) WHERE archived = 0;
-- Exactly one live root segment per track.
CREATE UNIQUE INDEX ux_segment_one_root
    ON segment(track_id) WHERE is_root = 1 AND archived = 0;

-- ─────────────────────────────────────────────────────────────────────────────
-- Task: the only first-class node. Always attaches to exactly one segment.
CREATE TABLE task (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id  INTEGER NOT NULL REFERENCES workspace(id) ON DELETE RESTRICT,
    segment_id    INTEGER NOT NULL REFERENCES segment(id)   ON DELETE RESTRICT, -- uniform parent
    status_id     INTEGER NOT NULL REFERENCES status(id)    ON DELETE RESTRICT,
    kind          TEXT,                              -- optional, single-valued work type (impl/review/research/...); NULL = untyped
    title         TEXT    NOT NULL,
    description   TEXT    NOT NULL DEFAULT '',
    priority      INTEGER NOT NULL DEFAULT 0,
    due_date      TEXT,
    start_date    TEXT,
    finish_date   TEXT,
    metadata_json TEXT    NOT NULL DEFAULT '{}',
    archived      INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX ix_task_segment ON task(segment_id) WHERE archived = 0;
CREATE INDEX ix_task_status  ON task(status_id)  WHERE archived = 0;
CREATE INDEX ix_task_kind    ON task(kind)        WHERE archived = 0 AND kind IS NOT NULL;

-- ─────────────────────────────────────────────────────────────────────────────
-- blocks: THE spine. task -> task, acyclic. Drives `next`/frontier.
CREATE TABLE blocks (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id   INTEGER NOT NULL REFERENCES workspace(id) ON DELETE RESTRICT,
    source_task_id INTEGER NOT NULL REFERENCES task(id)      ON DELETE RESTRICT, -- blocker
    target_task_id INTEGER NOT NULL REFERENCES task(id)      ON DELETE RESTRICT, -- blocked
    metadata_json  TEXT    NOT NULL DEFAULT '{}',
    archived       INTEGER NOT NULL DEFAULT 0,
    created_at     TEXT    NOT NULL DEFAULT (datetime('now')),
    CHECK (source_task_id <> target_task_id)
);
CREATE UNIQUE INDEX ux_blocks_live
    ON blocks(source_task_id, target_task_id) WHERE archived = 0;
CREATE INDEX ix_blocks_target_live
    ON blocks(target_task_id) WHERE archived = 0;

-- ─────────────────────────────────────────────────────────────────────────────
-- relates_to: decorative associations. task <-> task. Never affects `next`.
CREATE TABLE relates_to (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id   INTEGER NOT NULL REFERENCES workspace(id) ON DELETE RESTRICT,
    kind           TEXT    NOT NULL,                -- relates-to | mentions | spawns | ...
    source_task_id INTEGER NOT NULL REFERENCES task(id) ON DELETE RESTRICT,
    target_task_id INTEGER NOT NULL REFERENCES task(id) ON DELETE RESTRICT,
    metadata_json  TEXT    NOT NULL DEFAULT '{}',
    archived       INTEGER NOT NULL DEFAULT 0,
    created_at     TEXT    NOT NULL DEFAULT (datetime('now')),
    CHECK (source_task_id <> target_task_id)
);
CREATE UNIQUE INDEX ux_relates_live
    ON relates_to(kind, source_task_id, target_task_id) WHERE archived = 0;

-- ─────────────────────────────────────────────────────────────────────────────
-- Daemon-enforced invariants (not expressible in SQLite):
--   1. `blocks` forms a DAG (no cycles).
--   2. `segment.parent_segment_id` forms a tree within a track (no cycles).
--   3. Each track has exactly one root segment (is_root=1), auto-created with it.
--   4. Archiving a task archives its incident blocks/relates_to rows
--      (so a live edge always connects two live tasks — keeps `next` simple).
--   5. A segment's track_id is immutable and equals its root ancestor's track.
--
-- No journal table. History = append-only sidecar log (seq numbers, global w/
-- workspace field) in the XDG state dir, .gitignore'd, non-authoritative.
--
-- ─────────────────────────────────────────────────────────────────────────────
-- DEFERRED ADDITIONS (designed, not built — all are leaves: nothing references
-- them, so they add with zero migration pain whenever the need is real).
--
--   Agent claim / lease — concurrency coordination for >1 simultaneous agent.
--     Shape when added:
--       ALTER TABLE task ADD COLUMN claimed_by    TEXT;   -- framework-set
--       ALTER TABLE task ADD COLUMN claimed_until  TEXT;   -- framework-set expiry
--     Plus ONE daemon primitive: atomic "claim-if-free" (set claimed_by=me where
--       claimed_by IS NULL OR claimed_until <= now, in one txn, report win/lose),
--       and a fused next-and-claim built on it.
--     Frontier gains: AND (claimed_until IS NULL OR claimed_until <= now).
--     SoC: stx provides only the columns + the atomic primitive. TTL duration,
--       heartbeat/renew, crash policy, release-on-done all belong to the AGENT
--       FRAMEWORK, which passes claimed_until as a value. stx holds no policy.
--     Trigger to add: the moment a second concurrent agent runs.
--
--   (Labels were considered and REJECTED — stx is structurally dense enough that
--    a free-form key:value store would only duplicate tracks/status/priority or
--    become an unconstrained bypass of the self-defending schema. `task.kind`
--    covers the one real axis, single-valued.)
-- ─────────────────────────────────────────────────────────────────────────────
