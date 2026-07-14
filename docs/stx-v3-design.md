# stx v3.0.0 — Design

## Purpose

stx is a **datastore + frontier server for agent sessions**, run locally on a dev
machine to keep the dev and their local agents organized. You curate the structure
and descriptions; an agent reads `next` for *what to work on* and reads task/track
context for *what to know*. Context management lives **outside** the agent and is
owned **by you** — stx is what the agent reads, not a tracker of the agent.

It is not a JIRA replacement. JIRA (or whatever) remains the team system of record;
a track can hold a `jira_key` in its metadata as a back-reference, and that is the
entire relationship. stx tracks *your local work*; the org system tracks the org's.

Two principles drive the model:

1. **The agent never makes a context-merge decision.** stx hands over assembled,
   provenance-clear context, never a conflict to adjudicate.
2. **Each structure has one job.** Containment, dependency, and lifecycle are
   separate axes, never derived from one another.

---

## Vocabulary

```
workspace → track → segment* → task
```

- **workspace** — the local environment and the edge boundary. Holds many tracks.
  Edges never cross a workspace.
- **track** — a single coherent line of work (e.g. "auth"). ROOT-ONLY: never nests,
  has no parent. Carries track-level context (description + metadata). This is the
  primary `next` scope.
- **segment** — a nestable filing node under a track. PURE FILING: no metadata, no
  context, no inheritance. Exists only to organize tasks within a track.
- **task** — the only first-class node. Has a status, lives in exactly one segment,
  carries its own description + metadata, participates in the edge graphs. May
  optionally have a **`kind`** — a single-valued work type (impl / review /
  research / …) drawn from a per-workspace **registry** (the `task_kind` table,
  same controlled-vocabulary pattern as `status`; `NULL` = untyped). Registry-
  backed so `next --kind` never fragments on typos. Lets `next` filter by *what
  sort of work* is ready.

Edges (both task↔task):

- **blocks** — the spine. Directed, acyclic. Drives `next`/the frontier.
- **relates_to** — decorative association (relates-to, mentions, spawns, …). Cyclic
  OK. Never affects the frontier.

Lifecycle:

- **status** — a task's lifecycle stage; the kanban columns ARE statuses.
- **status_transition** — the per-workspace state machine; a move is legal iff a
  transition row exists. Cycles allowed (rework loops). No guards.

The user-facing vocabulary is plain work-language (track / segment / task / blocks /
relates-to / status). Graph vocabulary (DAG, frontier, topo-sort, node/edge) is
reserved for the engine internals and these design docs.

---

## The core asymmetry: tasks are nodes, tracks/segments are containers

Almost everything lives on the **task**: status, edges, description, metadata. The
track is a context-carrying root anchor; the segment is inert filing. This asymmetry
is what keeps the model simple — there is one kind of node and two kinds of
container, not a soup of symmetric "entities."

### Why three tiers (and why the track can't nest)

An earlier draft flattened containment to one level. That made `next`'s scope
ambiguous: with many same-level containers, "scope to this one" leaked across
siblings via cross-container dependencies, and the dev couldn't predict the result.

The fix: a **track is root-only** (no siblings problem within a line of work) and
**segments nest underneath it** (the epic→story→subtask filing devs actually use).
So `next --track T` has exactly one meaning — everything workable under T, however
deep the segments go — computed as a flat filter, no recursion. The dev's mental
unit (the track) and `next`'s scope unit line up.

---

## The two axes: status × track (orthogonal)

- **status** = *where in the lifecycle* a task is. Churns. The kanban columns.
- **track** = *what line of work* a task belongs to. Stable.

The kanban is `GROUP BY status` within a scope (a track, or the workspace). Neither
axis is derived from the other. "Is this track done?" is a *derived* question — are
all its live tasks terminal — not a stored track status. Tracks have no lifecycle.

---

## Status: a per-workspace state machine

- `status` rows define the stages; `terminal` marks done-ness (there is **no**
  separate `done` flag — terminal membership *is* done).
- `status_transition` defines legal moves, per-workspace, **cycles allowed**
  (`done → in-progress` rework is a legal back-edge).
- **No guards.** Transitions define legality only; preconditions like "finish all
  impl before review" are honored by the dev/agent, not enforced. Keeps the machine
  a declarative table, not a rules engine.

**Bootstrapping.** `task.status_id` is required (NOT NULL + FK), so a workspace with
no statuses can hold no task. Workspace creation therefore **seeds a default status
set in the same transaction** — `todo / in-progress / done` (with `done` terminal),
sensible `kanban_order`, and the obvious transitions including the `done → in-progress`
rework back-edge. The **create-time default** status (used when a task is created
without an explicit status) is marked by a stored **`is_default` flag** on `status` —
deliberately decoupled from `kanban_order` so the task entry-point and the kanban
display order stay independent axes (the same "each structure has one job" discipline
as status × track). Exactly one live default per workspace is DB-enforced by a partial
unique index (`ux_status_one_default`, the same singleton idiom as the root segment's
`is_root`); the seed sets it on `todo`, a set-default verb moves it, and archiving the
current default is rejected ("set another default first" — symmetric with the
root-segment archive reject in #6). The dev can rename/extend the set afterward; the
seed only guarantees a workspace is usable the moment it exists.

The daemon can answer "legal moves from here" as a one-hop lookup — the agent's
action space.

---

## Containment & context: filing-only, no inheritance

Segments nest but are **pure filing** — they carry no metadata and contribute
nothing to context. Therefore:

- A task's context is its **own** description + metadata plus, at most, its
  **track's** context. One hop, no ancestry walk through the segment tree.
- Metadata is **Stored-only**: each task and each track owns its blob; nothing
  resolves or inherits. There is no merge policy because there is never anything to
  merge — which is exactly what satisfies Principle 1.

**metadata is non-load-bearing.** The engine never branches on `metadata_json` —
`next`, the status machine, and all nine invariants ignore it entirely. It is an
inert escape hatch, not protected state, and *that* is why it is safe: an agent
writing junk there cannot corrupt anything the engine relies on. This is also why
rejecting labels is not a contradiction (a `metadata_json` blob is itself free-form
and fine) — labels were rejected for duplicating queried structure, not for being
free-form. The invariant to preserve forever: **the engine reads no free-form
field.**

Tasks attach to a segment uniformly: every track auto-creates one **root segment**,
and "add a task to the track" routes it there. So a task always has exactly one
`segment_id` (no track-or-segment polymorphism), and a simple track needs no manual
segments at all.

---

## Edges: blocks (spine) vs relates_to (decorative)

- **blocks** — task→task, acyclic (enforced in the daemon). `next` topo-sorts this
  and nothing else. Many blocks per task is expected; encoding real dependencies up
  front is the planning value that lets the agent order work without guessing.
- **relates_to** — task↔task, free-form `kind`, cyclic OK, never touches the
  frontier. `spawns` (provenance) lives here — it records causality, not ordering.
  Stored **directed** (source→target), and the unique index is directed too — which is
  correct, because some kinds *are* directional: `spawns` A→B ≠ B→A, so both rows must
  be allowed to coexist. The cost is that genuinely **symmetric** kinds (`relates-to`,
  `mentions`) can accumulate a reciprocal pair (A→B and B→A); that is accepted, not
  prevented — no canonicalization, since it would corrupt the directional kinds. The
  read absorbs it: "what relates to X" UNIONs both directions and **dedups** for
  display. So the symmetry is a read-side contract, not a storage constraint. The
  free-form `kind` is a *deliberate* power-user choice, not an oversight (decision
  D6): it is never constrained to a vocabulary. `stx relate-kinds` lists the kind
  values in live use so a user can self-check for drift (`relates-to` vs
  `relates_to`) without a hard constraint.

Phase gates (impl-before-review) are a **status** concern, not an edge: they are not
modeled as track/segment edges. Containers are never edge endpoints; only tasks are.

---

## `next` (the frontier)

`next` is a **filter, not a recommender**: it returns the ready set (tasks you can
act on now) and makes no prioritization decision. A task is in the frontier iff it
is not archived, not terminal, and has no live `blocks` edge from a non-terminal
task. In-progress tasks stay in. Output is ordered `priority DESC, id ASC` for
*stable presentation only* — the consumer (dev or agent) does any real ranking.

Scope: workspace always required; narrow to a **track** (the common call) via a flat
`segment.track_id` filter; a **segment-subtree** filter exists but is documented
carefully (the one scope where the in/out boundary isn't obvious). Cross-track
`blocks` dependencies still gate correctly — a dependency is a dependency regardless
of which track each task is filed under.

Full spec and verified queries: see `stx-v3-next.md`.

---

## Journal: gone as a table; history is a log4j2 journal

No journal/audit table. Session history, if wanted, is a **log4j2 journal** outside
SQLite: a dedicated `stx.journal` logger → rolling file in the XDG state dir,
`.gitignore`'d, throwaway, **non-authoritative** (SQLite is the source of truth; the
journal is write-only and never read back to determine state). One JSON line per
committed mutation, global with a `workspace` field and a timestamp. **No `seq`
field** — a single writer (the write-actor) emits in commit order, so the file's line
order *is* the event order, and the timestamp covers human/cross-run reading. A
durable, restart-surviving cursor (the only kind of `seq` worth having) is deferred —
added as a one-row SQLite counter only if a real subscription/notification consumer
ever lands. Versioning core entities is off the table — heavier than a journal, not
lighter.

---

## Architecture: daemon as single writer

A long-lived **daemon** is the sole writer; clients talk to it rather than opening
SQLite directly. Single ordered write path makes the journal clean *logging* rather
than after-the-fact *auditing*. `next` may simply **recompute on read** — at
solo-dev scale (hundreds–low-thousands of tasks) a topo-sort is microseconds, and
recompute-on-read is *more correct* than incremental caching because rework
(reopening a done task) re-derives the frontier with no stale-cache risk. A warm
in-memory frontier is a later optimization, not a requirement. WAL mode is the
entire concurrency story (single writer, multiple readers).

The bar is "faster and more structured than a TODO.md," not throughput. Verbs stay
atomic and small (create/update/move/edge/archive + `next`); bulk = a loop of
single creates.

### Optimistic locking: ordering is not conflict detection

The single writer guarantees writes are *ordered and atomic* — never corrupt. It
does **not** guarantee they aren't *stale*: the actor can't see that a command was
computed from an out-of-date read. (Reads are separately snapshot-isolated *within a
request* — each read runs in a deferred WAL transaction, so a multi-statement read
never sees a torn mid-write state. That is orthogonal to the cross-request staleness
below, which is what the two tools address.) Two problems hide here, and they need
different tools:

- **Lost update** (two agents edit the same task off the same read; last write
  silently wins) → **optimistic locking.** Each mutable row carries a monotonic
  `version`; every edit of an existing row is a compare-and-set on it, and a
  mismatch returns a conflict carrying the current row for the agent to re-plan.
  Added now (cheap, helps even a lone agent racing the human).
- **Double-work** (two agents both *pick* the same ready task) → the deferred
  **claim/lease**, not locking. OL on a status move gives an interim
  first-mover-wins, but only at the move instant — it does not reserve a task for
  the duration of work. That reservation stays deferred until a second concurrent
  agent actually runs.

OL is correctness of edits; the lease is reservation of work — and claim-if-free is
itself an OL-style CAS, so the two share one mechanism with no rework.

---

## Daemon-enforced invariants (not expressible in SQLite)

1. `blocks` forms a DAG (no cycles).
2. `segment.parent_segment_id` forms a tree within a track (no cycles).
3. Each track has exactly one root segment, auto-created with it.
4. Archiving a task archives its incident `blocks`/`relates_to` rows, so a live
   edge always connects two live tasks (keeps `next` simple). *Corollary:*
   archiving an incomplete blocker auto-unblocks its dependents (the edge is
   gone) — intended behavior; archived means does-not-exist.
5. A segment's `track_id` is immutable and equals its root ancestor's track.
6. **Container archive cascade.** Archiving a track archives, in the same
   transaction, all its live segments and all live tasks filed under them (each
   task archive cascades its edges via #4). Archiving a **segment** archives, in
   the same transaction, its descendant segments (walking `parent_segment_id`
   downward) and all live tasks filed under any of them — so a mid-tree segment
   archive can never orphan its descendants. A **root** segment is not archived
   directly (only via its track's cascade); reject a direct root-segment archive.
   Archiving a workspace cascades the same way down through its tracks. This is the
   write-time *integrity* guarantee. Reads do not trust it alone: list/frontier/
   kanban queries select from the `live_task` view (own-segment + track +
   workspace all unarchived) as defense-in-depth, and an assertion ("no live task
   under an archived container, including an archived ancestor segment") surfaces a
   cascade bug rather than letting the view silently mask it. The view stays a flat
   check (own segment only); the *recursion* for an archived ancestor segment is
   the segment cascade's job, not the read path's.
7. **Edges never cross a workspace.** Before inserting a `blocks`/`relates_to`
   row, the daemon verifies source and target share a workspace (reject
   otherwise) and derives `edge.workspace_id` from it (never caller-supplied).
8. **Workspace coherence on every FK write.** The scalar counterpart to #7:
   SQLite FKs reference a table, not a workspace-scoped subset, so the daemon
   checks same-workspace on each cross-row reference. On task create/edit,
   `status_id`, `kind_id` (if set), and `segment_id` must all belong to the task's
   workspace; on task create, `task.workspace_id` is **derived** from the segment's
   `track.workspace_id` (never caller-supplied), so the task↔container chain cannot
   drift. On `status_transition` create, both endpoints belong to the transition's
   workspace; on segment create, `parent_segment_id` shares the new segment's track
   and workspace. Without #8 an agent could point a task at another workspace's
   status/kind — the `live_task` view joins both `task.workspace_id` and
   `segment→track→workspace` but never asserts they are equal, so only the daemon
   closes this hole.
9. **No live task references an archived status or kind.** RESTRICT FKs block only
   delete, not archive, so retiring a status/kind that a live task still uses would
   orphan it. Enforced per axis: **status archive is rejected** while any live task
   has that status (status is load-bearing — terminal/`next`/kanban — and `status_id`
   is non-null, so auto-reassign would be unsafe magic); a successful status archive
   also cascade-archives its incident `status_transition` rows (same txn, like #4).
   **kind archive null-cascades** instead — it sets `kind_id = NULL` on referencing
   live tasks (kind is optional; `NULL` is its natural "untyped" value), so no reject
   is needed. (Archiving the default status is separately rejected — see Status.)

---

## Deferred & rejected additions

The model's load-bearing entities (workspace, track, status, the edge graphs) are
referenced everywhere and had to be right up front. Everything below is a **leaf** —
nothing references it — so it adds later with zero migration pain. The rule: *if
nothing else points at a thing, ship without it and add it the day the lack is felt.*

**Added now — `task.kind`.** One optional, single-valued work-type, drawn from a
per-workspace `task_kind` registry (controlled vocabulary, like `status`). Earns
its place (sharpens what an agent picks up) without the risks of a general label
system, and — being registry-backed — without typo fragmentation of the one axis
`next --kind` depends on. Unlike `status`, the registry is **not auto-seeded** — it
starts empty and the dev populates it the day a kind is felt (kind is optional;
typo-safety comes from the registry mechanism, not from pre-population).

**Deferred — agent claim / lease.** Concurrency coordination for >1 simultaneous
agent. Two nullable columns (`claimed_by`, `claimed_until`) plus one daemon
primitive: an atomic *claim-if-free*, with a fused *next-and-claim*. The frontier
gains `AND (claimed_until IS NULL OR claimed_until <= now)`. **SoC boundary:** stx
provides only the columns and the atomic primitive; the *policy* — TTL duration,
heartbeat/renew, crash handling, release-on-done — belongs to the **agent
framework**, which passes `claimed_until` as a value. stx holds no coordination
opinion; it only offers the mutual-exclusion primitive that agents can't build for
themselves on a non-atomic store. **Trigger:** the moment a second concurrent agent
runs. Failure mode if not yet added: silent double-work (recoverable, not
corrupting).

**Rejected — general labels / tags.** Considered and declined, on **duplication**
grounds. stx is structurally dense (tracks, segments, status, two edge types,
priority, kind) — a free-form `key:value` store would mostly duplicate existing
structure (`area:auth` = a track) or shadow it (`blocked`, `urgent` = derivable /
priority). The Obsidian case for tags (filling a structural vacuum) doesn't apply
where there is no vacuum. `task.kind` covers the single real axis.

The rejection is *not* "free-form fields are unsafe" — see **metadata is
non-load-bearing** (Containment & context); `metadata_json` is itself a free-form
field and is fine.
The danger of a label axis is specifically that it would be a *queried* dimension
duplicating structure the engine already owns.

---

## Status of decisions

**Settled:** workspace→track→segment→task hierarchy; track is root-only and
context-carrying; segments are pure filing; task is the only node; uniform task
parentage via auto root segment; status is a per-workspace transition machine
(cycles, no guards); `done` = terminal membership; metadata Stored-only with
one-hop context; `blocks` (acyclic, task→task) is the entire spine; `relates_to`
decorative; optional single-valued `task.kind`; `next` is a filter returning the
frontier, track-scoped by default-ish
(workspace required); journal table removed, history is a non-authoritative log4j2
journal; daemon is single writer, recompute-on-read.

**Open / deferred:** agent claim/lease (see Deferred additions above); durable
journal cursor (restart-surviving seq); inverse read (`why <task>` /
`blocked`); optional unblock-impact annotation on `next`; daemon verb/RPC surface;
TUI (out of scope this pass).
