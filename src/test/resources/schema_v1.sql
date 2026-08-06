-- stx v3.0.0 — clean schema. On-disk version is tracked via SQLite's PRAGMA user_version
-- (stamped to Db.SCHEMA_VERSION on fresh load). Forward migrations live in resources/migrations/
-- as NNN_name.sql and are applied in order by Db at startup (mirrors ~/code/stx's runner):
-- fresh DB (user_version=0) loads this file whole; an older DB runs the pending migrations.
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
--   * No journal table; history is a non-authoritative log4j2 journal outside SQLite.

PRAGMA foreign_keys = ON;

-- ─────────────────────────────────────────────────────────────────────────────
CREATE TABLE workspace (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT    NOT NULL,
    metadata_json TEXT    NOT NULL DEFAULT '{}',
    archived      INTEGER NOT NULL DEFAULT 0,
    version       INTEGER NOT NULL DEFAULT 0,       -- optimistic-lock token (see CAS note at foot)
    created_at    TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT    NOT NULL DEFAULT (datetime('now')),
    CHECK (archived IN (0, 1)),
    CHECK (length(trim(name)) > 0),
    CHECK (json_valid(metadata_json) AND json_type(metadata_json) = 'object')  -- object-shaped k/v (the daemon gate mirrors this)
);

-- ─────────────────────────────────────────────────────────────────────────────
-- Status: lifecycle stage. The kanban columns ARE statuses.
--   BOOTSTRAP: task.status_id is NOT NULL with an FK, so a workspace with zero
--   statuses can accept no task. Workspace creation MUST seed a default status set
--   in the SAME transaction — Backlog(kanban_order=0, is_default=1) / Implementation(1) /
--   Review(2) / Done(3, terminal=1) — plus the forward transitions and rework
--   back-edges (Implementation->Backlog, Review->Implementation, Done->Review). The create-time default status (used when
--   a task is created without an explicit status_id) is the live status flagged
--   is_default=1 — a STORED flag, not derived from kanban_order, so the entry-point
--   and the display order are independent. ux_status_one_default backs "at most one
--   live default per workspace"; the seed provides the one. Moving it is a
--   set-default verb (clear old + set new in one txn). Archiving the default status
--   is REJECTED ("set another default first") — symmetric with the root-segment
--   archive reject in invariant #6.
CREATE TABLE status (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id INTEGER NOT NULL REFERENCES workspace(id) ON DELETE RESTRICT,
    name         TEXT    NOT NULL,
    kanban_order INTEGER NOT NULL DEFAULT 0,        -- display order only
    terminal     INTEGER NOT NULL DEFAULT 0,        -- terminal == "done"
    is_default   INTEGER NOT NULL DEFAULT 0,        -- create-time entry status; exactly one live per ws (see index)
    archived     INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT    NOT NULL DEFAULT (datetime('now')),
    CHECK (terminal IN (0, 1) AND is_default IN (0, 1) AND archived IN (0, 1)),
    CHECK (length(trim(name)) > 0),
    -- The create-time default status is where tasks are BORN, so it must not be terminal:
    -- a terminal default births every task "done" and instantly invisible to `next`. The
    -- daemon (setDefaultStatus) rejects it with a clean error; this CHECK is the backstop.
    CHECK (NOT (is_default = 1 AND terminal = 1))
);
CREATE UNIQUE INDEX ux_status_ws_name_live
    ON status(workspace_id, name) WHERE archived = 0;
-- Exactly one live default status per workspace (mirrors ux_segment_one_root).
-- Decouples the task entry-point from kanban_order (display order); the index
-- enforces "at most one", the seed guarantees "at least one".
CREATE UNIQUE INDEX ux_status_one_default
    ON status(workspace_id) WHERE is_default = 1 AND archived = 0;

-- ─────────────────────────────────────────────────────────────────────────────
-- Status transitions: per-workspace state machine. Cycles allowed. No guards.
CREATE TABLE status_transition (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id   INTEGER NOT NULL REFERENCES workspace(id) ON DELETE RESTRICT,
    from_status_id INTEGER NOT NULL REFERENCES status(id)    ON DELETE RESTRICT,
    to_status_id   INTEGER NOT NULL REFERENCES status(id)    ON DELETE RESTRICT,
    archived       INTEGER NOT NULL DEFAULT 0,
    CHECK (from_status_id <> to_status_id),
    CHECK (archived IN (0, 1))
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
    version       INTEGER NOT NULL DEFAULT 0,        -- optimistic-lock token (see CAS note at foot)
    created_at    TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT    NOT NULL DEFAULT (datetime('now')),
    -- No parent: tracks exist only at the root level.
    CHECK (archived IN (0, 1)),
    CHECK (length(trim(name)) > 0),
    CHECK (json_valid(metadata_json) AND json_type(metadata_json) = 'object')
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
    CHECK (parent_segment_id IS NULL OR parent_segment_id <> id),   -- no self-parent
    -- A root segment has parent_segment_id IS NULL. Deeper cycle prevention: daemon.
    CHECK (is_root IN (0, 1) AND archived IN (0, 1)),
    CHECK (length(trim(name)) > 0)
);
CREATE INDEX ix_segment_track  ON segment(track_id)          WHERE archived = 0;
CREATE INDEX ix_segment_parent ON segment(parent_segment_id) WHERE archived = 0;
-- Exactly one live root segment per track.
CREATE UNIQUE INDEX ux_segment_one_root
    ON segment(track_id) WHERE is_root = 1 AND archived = 0;

-- ─────────────────────────────────────────────────────────────────────────────
-- Task kind: per-workspace registry of work types (impl/review/research/...).
--   Mirrors `status` — a controlled vocabulary, not free text, so `next --kind`
--   never fragments on typos (impl vs Impl vs implementation). Single-valued on
--   the task via kind_id; NULL = untyped. Registry starts EMPTY — NOT auto-seeded
--   (unlike `status`, which is mandatory because task.status_id is NOT NULL). kind is
--   optional, so a workspace is usable with zero kinds; the dev registers kinds before
--   use. Typo-safety holds regardless of seeding — only registered kind_ids are settable.
CREATE TABLE task_kind (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id INTEGER NOT NULL REFERENCES workspace(id) ON DELETE RESTRICT,
    name         TEXT    NOT NULL,
    archived     INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT    NOT NULL DEFAULT (datetime('now')),
    CHECK (archived IN (0, 1)),
    CHECK (length(trim(name)) > 0)
);
CREATE UNIQUE INDEX ux_task_kind_ws_name_live
    ON task_kind(workspace_id, name) WHERE archived = 0;

-- ─────────────────────────────────────────────────────────────────────────────
-- Task: the only first-class node. Always attaches to exactly one segment.
CREATE TABLE task (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id  INTEGER NOT NULL REFERENCES workspace(id) ON DELETE RESTRICT,
    segment_id    INTEGER NOT NULL REFERENCES segment(id)   ON DELETE RESTRICT, -- uniform parent
    status_id     INTEGER NOT NULL REFERENCES status(id)    ON DELETE RESTRICT,
    kind_id       INTEGER          REFERENCES task_kind(id) ON DELETE RESTRICT, -- optional work type; NULL = untyped
    title         TEXT    NOT NULL,
    description   TEXT    NOT NULL DEFAULT '',
    priority      INTEGER NOT NULL DEFAULT 0,
    metadata_json TEXT    NOT NULL DEFAULT '{}',
    archived      INTEGER NOT NULL DEFAULT 0,
    version       INTEGER NOT NULL DEFAULT 0,        -- optimistic-lock token (see CAS note at foot)
    created_at    TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT    NOT NULL DEFAULT (datetime('now')),
    CHECK (archived IN (0, 1)),
    CHECK (length(trim(title)) > 0),
    CHECK (json_valid(metadata_json) AND json_type(metadata_json) = 'object')
);
CREATE INDEX ix_task_workspace ON task(workspace_id) WHERE archived = 0;  -- hot path: every `next` filters workspace_id first
CREATE INDEX ix_task_segment   ON task(segment_id)   WHERE archived = 0;
CREATE INDEX ix_task_status    ON task(status_id)    WHERE archived = 0;
CREATE INDEX ix_task_kind      ON task(kind_id)      WHERE archived = 0 AND kind_id IS NOT NULL;

-- ─────────────────────────────────────────────────────────────────────────────
-- live_task: the canonical "visible task" predicate, centralized so every
-- list/frontier/kanban read applies the SAME defensive check (partial
-- application would make a task visible in one view, hidden in another). A task
-- is visible iff it AND its flat container chain (own segment, track, workspace)
-- are all unarchived. This is defense-in-depth: cascade (invariant #6) is the
-- write-time integrity guarantee; this view keeps reads correct even if a
-- cascade bug ever leaves an orphan. Mid-tree segment archival (an archived
-- ANCESTOR segment) is intentionally NOT checked here — that needs a recursive
-- parent_segment_id walk, which would re-import the recursion the flat design
-- avoids; the segment-archive cascade (invariant #6) owns that case, archiving
-- every descendant task so none can be left live under an archived ancestor
-- segment. NB: this is for LIST reads — a direct
-- GET /tasks/{id} may bypass the view to inspect an archived row on purpose.
CREATE VIEW live_task AS
SELECT t.*
FROM task t
JOIN segment   s ON s.id = t.segment_id
JOIN track     k ON k.id = s.track_id
JOIN workspace w ON w.id = t.workspace_id
WHERE t.archived = 0 AND s.archived = 0 AND k.archived = 0 AND w.archived = 0;

-- ─────────────────────────────────────────────────────────────────────────────
-- blocks: THE spine. task -> task, acyclic. Drives `next`/frontier.
CREATE TABLE blocks (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    workspace_id   INTEGER NOT NULL REFERENCES workspace(id) ON DELETE RESTRICT,
    source_task_id INTEGER NOT NULL REFERENCES task(id)      ON DELETE RESTRICT, -- blocker
    target_task_id INTEGER NOT NULL REFERENCES task(id)      ON DELETE RESTRICT, -- blocked
    archived       INTEGER NOT NULL DEFAULT 0,
    CHECK (source_task_id <> target_task_id),
    CHECK (archived IN (0, 1))
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
    archived       INTEGER NOT NULL DEFAULT 0,
    CHECK (source_task_id <> target_task_id),
    CHECK (archived IN (0, 1))
);
CREATE UNIQUE INDEX ux_relates_live
    ON relates_to(kind, source_task_id, target_task_id) WHERE archived = 0;

-- ─────────────────────────────────────────────────────────────────────────────
-- Daemon-enforced invariants (not expressible in SQLite):
--   CANONICAL SOURCE: this list is restated in stx-v3-design.md and
--   stx-v3-implementation-brief.md §3 for readability — same rules. This file is
--   authoritative for data SHAPE; the brief for build behavior. Change one copy ->
--   change all (grep the rule across docs/) to avoid drift.
--   1. `blocks` forms a DAG (no cycles).
--   2. `segment.parent_segment_id` forms a tree within a track (no cycles).
--   3. Each track has exactly one root segment (is_root=1), auto-created with it.
--   4. Archiving a task archives its incident blocks/relates_to rows
--      (so a live edge always connects two live tasks — keeps `next` simple).
--      Corollary: archiving an incomplete blocker auto-unblocks its dependents
--      (the edge is gone) — intended; archived == does-not-exist.
--   5. A segment's track_id is immutable and equals its root ancestor's track.
--   6. Container archive cascade. Archiving a track archives — in the SAME
--      transaction — all its live segments and all live tasks filed under them
--      (each task archive cascades its edges via #4). Archiving a SEGMENT archives,
--      in the same txn, its descendant segments (walk parent_segment_id downward)
--      and all live tasks filed under any of them. Archiving a workspace cascades
--      the same way down through its tracks. So every container archive (workspace/
--      track/segment) leaves NO live task under an archived ancestor of any tier.
--      A root segment is NOT archived directly (only via its track's cascade) —
--      reject a direct root-segment archive. This is the write-time INTEGRITY
--      guarantee. Reads do NOT rely on it alone: list/frontier/kanban queries go
--      through the `live_task` view (defense-in-depth), and a test/startup
--      ASSERTION checks "no live task under an archived container (incl. an
--      archived ancestor segment)" so a cascade bug surfaces instead of being
--      silently masked by the view.
--   7. Edges never cross a workspace. Before inserting a blocks/relates_to row,
--      the daemon verifies source and target tasks share a workspace (reject
--      otherwise) and sets edge.workspace_id from that shared workspace. The
--      column is daemon-derived, never caller-supplied.
--   8. Workspace coherence on every FK write (the scalar counterpart to #7 —
--      SQLite's FKs reference a table, not a workspace-scoped subset, so the
--      daemon must check same-workspace on each cross-row reference):
--        * task create/edit: task.status_id, task.kind_id (if non-NULL), and
--          task.segment_id all belong to task.workspace_id.
--        * task create: task.workspace_id is DERIVED from its segment's
--          track.workspace_id (never caller-supplied — same discipline as #7's
--          edge.workspace_id), so the task/container chain can never drift.
--        * status_transition create: from_status_id and to_status_id both belong
--          to transition.workspace_id.
--        * segment create: parent_segment_id (if set) shares the new segment's
--          track_id and workspace_id.
--      Reject a mismatch (typed CrossWorkspace failure, mirroring #7). Without
--      this, an agent could point a task at another workspace's status/kind or
--      drift task.workspace_id from its container chain — the `live_task` view
--      joins both task.workspace_id AND segment->track->workspace but does not
--      assert they are equal, so only the daemon closes this hole.
--   9. No live task references an archived status or kind. RESTRICT FKs block only
--      DELETE, not archive — so archiving a status/kind a live task still points at
--      would orphan that task. Enforced per axis:
--        * status archive: REJECT if any live task has that status_id (Validation,
--          "move those tasks first") — status is load-bearing (terminal/next/kanban),
--          auto-reassign is unsafe and status_id is NOT NULL. On success also archive
--          its incident status_transition rows (from_status_id or to_status_id = it),
--          same txn — like the edge cascade #4, so no live transition points at a dead
--          status. (Archiving the DEFAULT status is separately rejected; see the
--          status-table BOOTSTRAP note / ux_status_one_default.)
--        * kind archive: NULL-CASCADE — set task.kind_id = NULL on every live task
--          referencing it, same txn, then archive the kind. kind is optional; NULL is
--          its natural "untyped" value, so no reject is needed.
--
-- No journal table. History = log4j2 journal (dedicated stx.journal appender, JSON
-- lines, global w/ workspace field + timestamp; NO seq — order = single-writer append
-- order) in the XDG state dir, .gitignore'd, non-authoritative, write-only. Durable
-- cross-restart cursor deferred (a one-row SQLite meta counter) until a real subscriber
-- needs it.
--
-- ─────────────────────────────────────────────────────────────────────────────
-- Optimistic locking (lost-update protection for concurrent local agents):
--   The write-actor serializes writes (ordering) but cannot see that a command
--   was computed from a STALE read. `version` is a monotonic per-row token
--   (NOT updated_at — that is second-granularity and collides sub-second).
--   Every edit of an EXISTING row is a conditional compare-and-set:
--       UPDATE <tbl> SET <fields>, version = version + 1, updated_at = datetime('now')
--        WHERE id = :id AND archived = 0 AND version = :expected;
--     changes()=1 -> ok (return new version).
--     changes()=0 -> re-read: different version => 409 CONFLICT (return current
--                    row so the agent re-plans); missing/archived => 404/410.
--   Reads return `version`; mutating-existing commands carry `expected_version`.
--   NOT versioned: creates (no prior version), edge tables (append-only; their
--   invariants re-validate live), segments (pure filing, not edited). A status
--   move is OL'd on the task -> interim first-mover-wins coordination (the loser
--   gets 409 and picks another `next` task); it arbitrates the move INSTANT only,
--   not work duration -> that gap is the deferred claim/lease below.
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
--       and a fused next-and-claim built on it. NB: claim-if-free is itself an
--       OL-style CAS (same mechanism as `version` above) — no rework when added.
--       OL = correctness of edits (no lost updates); lease = reservation of work
--       (no double-work). Different problems; OL is not a substitute for the lease.
--     Frontier gains: AND (claimed_until IS NULL OR claimed_until <= now).
--     SoC: stx provides only the columns + the atomic primitive. TTL duration,
--       heartbeat/renew, crash policy, release-on-done all belong to the AGENT
--       FRAMEWORK, which passes claimed_until as a value. stx holds no policy.
--     Trigger to add: the moment a second concurrent agent runs.
--
--   (Labels were considered and REJECTED — stx is structurally dense enough that
--    a free-form key:value store would only DUPLICATE existing structure
--    (area:auth = a track; blocked/urgent = derivable / priority). The kind_id
--    registry covers the one real axis, single-valued. NB: metadata_json is NOT
--    a counter-example — the engine never reads it (see design.md), so it is an
--    inert escape hatch, not protected state. Labels were rejected for
--    duplication, not for being free-form.)
-- ─────────────────────────────────────────────────────────────────────────────
