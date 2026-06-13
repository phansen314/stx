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
  research / …, user-defined, free-text, `NULL` = untyped) that lets `next` filter
  by *what sort of work* is ready.

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

## Journal: gone; history is a sidecar

No journal/audit table. Session history, if wanted, is an **append-only sidecar
log** outside SQLite: XDG state dir, `.gitignore`'d, throwaway, **non-authoritative**
(SQLite is the source of truth; the log is never read back to determine state).
Monotonic **seq numbers**, global with a `workspace` field. Versioning core entities
is off the table — heavier than a journal, not lighter.

---

## Architecture: daemon as single writer

A long-lived **daemon** is the sole writer; clients talk to it rather than opening
SQLite directly. Single ordered write path makes the sidecar clean *logging* rather
than after-the-fact *auditing*. `next` may simply **recompute on read** — at
solo-dev scale (hundreds–low-thousands of tasks) a topo-sort is microseconds, and
recompute-on-read is *more correct* than incremental caching because rework
(reopening a done task) re-derives the frontier with no stale-cache risk. A warm
in-memory frontier is a later optimization, not a requirement. WAL mode is the
entire concurrency story (single writer, multiple readers).

The bar is "faster and more structured than a TODO.md," not throughput. Verbs stay
atomic and small (create/update/move/edge/archive + `next`); bulk = a loop of
single creates.

---

## Daemon-enforced invariants (not expressible in SQLite)

1. `blocks` forms a DAG (no cycles).
2. `segment.parent_segment_id` forms a tree within a track (no cycles).
3. Each track has exactly one root segment, auto-created with it.
4. Archiving a task archives its incident `blocks`/`relates_to` rows, so a live
   edge always connects two live tasks (keeps `next` simple).
5. A segment's `track_id` is immutable and equals its root ancestor's track.

---

## Deferred & rejected additions

The model's load-bearing entities (workspace, track, status, the edge graphs) are
referenced everywhere and had to be right up front. Everything below is a **leaf** —
nothing references it — so it adds later with zero migration pain. The rule: *if
nothing else points at a thing, ship without it and add it the day the lack is felt.*

**Added now — `task.kind`.** One optional, single-valued work-type column. Earns its
place (sharpens what an agent picks up) without the risks of a general label system.

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

**Rejected — general labels / tags.** Considered and declined. stx is structurally
dense (tracks, segments, status, two edge types, priority, kind) — a free-form
`key:value` store would mostly duplicate existing structure (`area:auth` = a track)
or shadow it dangerously (`blocked`, `urgent` = derivable / priority), and an
unconstrained field is the one addition that *undermines* the self-defending schema
by giving agents a place to write state the invariants don't protect. The Obsidian
case for tags (filling a structural vacuum) doesn't apply where there is no vacuum.
`task.kind` covers the single real axis.

---

## Status of decisions

**Settled:** workspace→track→segment→task hierarchy; track is root-only and
context-carrying; segments are pure filing; task is the only node; uniform task
parentage via auto root segment; status is a per-workspace transition machine
(cycles, no guards); `done` = terminal membership; metadata Stored-only with
one-hop context; `blocks` (acyclic, task→task) is the entire spine; `relates_to`
decorative; optional single-valued `task.kind`; `next` is a filter returning the
frontier, track-scoped by default-ish
(workspace required); journal removed, history is a non-authoritative sidecar;
daemon is single writer, recompute-on-read.

**Open / deferred:** agent claim/lease (see Deferred additions above); sidecar
event schema details; inverse read (`why <task>` /
`blocked`); optional unblock-impact annotation on `next`; daemon verb/RPC surface;
TUI (out of scope this pass).
