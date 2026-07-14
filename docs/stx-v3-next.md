# stx v3.0.0 — `next` specification

## What `next` is

`next` is a **filter, not a recommender.** It returns the *ready set* — the tasks
you are currently able to act on — and makes **no** prioritization decision on your
behalf. Ranking, picking a winner, "do the highest-impact thing" — all of that is
left to the human or agent consuming the output. This matches stx's philosophy: you
manage the work; stx surfaces the workable surface, it doesn't decide for you.

Mechanically, `next` returns the actionable tasks of the `blocks` DAG — roughly
an **antichain** (no returned task blocks another via unfinished work), though
terminal tasks sitting mid-chain mean it isn't a strict antichain of the raw graph.
Deterministic, explainable, no tunable knobs.

## Eligibility rule

A task is in the frontier **iff all** of:

1. `archived = 0`
2. its status is **not** terminal
3. **no** live `blocks` points at it from a **non-terminal** task

That is the entire rule. In-progress tasks stay in (they are workable). The only
exclusions are: archived, terminal, or blocked-by-something-unfinished.

### Why the query stays simple: the archive invariant

Archiving a task **auto-archives its incident `blocks` rows** (daemon-enforced,
in the same transaction). Therefore a *live* `blocks` always connects two *live*
tasks. `next` never has to check a blocker's archived status — a live edge cannot
point at an archived task by construction. The eligibility check reduces to "no live
blocker that is non-terminal."

This is a write-time invariant the daemon owns (alongside blocks-DAG acyclicity) —
SQLite's archive-only / RESTRICT design does not cascade, so the daemon maintains it.

The same write-time discipline covers **containers**: archiving a track or
workspace cascades down to archive its tasks (daemon invariant #6). That cascade is
the integrity guarantee; the read path does not trust it blindly — see below.

### Defensive visibility — the `live_task` view

`next` (and every list/kanban read) selects from the **`live_task` view**, not bare
`task`. A task is visible iff it AND its flat container chain — own segment, track,
workspace — are all unarchived. Two reasons this is worth the extra joins:

- **Defense-in-depth.** Cascade (#6) *should* mean no live task sits under an
  archived container. The view makes `next` correct **even if that ever fails** —
  a cascade bug, or an out-of-band DB edit, can't leak an orphan into the frontier.
  Reads being independently correct matters for a store agents write to.
- **Centralized once.** Visibility is defined in one place (the view), so `next`,
  kanban, and track listings apply the *identical* predicate. Sprinkling
  `AND archived = 0` per query risks a task that's visible in one view and hidden
  in another.

Two deliberate boundaries:

1. **Flat only.** The view checks the task's *own* segment, plus track and
   workspace (via the denormalized `segment.track_id`). It does **not** walk
   `parent_segment_id` to check an archived *ancestor* segment — that recursion is
   exactly what the flat design avoids. An archived ancestor segment is handled at
   *write* time by the segment-archive cascade (invariant #6: archiving a segment
   archives its whole subtree of segments + tasks), so no live task can sit under
   one — the read path never needs the recursive ancestor walk.
2. **Masking vs. surfacing.** A defensive view can *hide* the symptom of a cascade
   bug. So it is paired with an assertion (test / startup check): "no live task
   sits under an archived container (including an archived ancestor segment)." The
   view keeps results correct; the assertion makes the bug visible instead of silent.

## Output

- Returns the **whole ready set** (not a single task). `--limit N` for top-N.
- **Workspace scope is always required.** Optionally filter to a **track** (the
  common call — "what's workable in this story"). A **segment-subtree** filter also
  exists but is documented carefully, because segment scoping is the one place a dev
  can still surprise themselves about what's in/out of scope.
    - `next --workspace W`            → everything workable in the workspace
    - `next --workspace W --track G`  → workable within track G (the primary call)
    - `next --workspace W --segment F` → workable within segment F's subtree (see docs)
- **Optional `--kind K` filter** (orthogonal to scope): restrict the frontier to
  tasks of a given work type, e.g. `next --workspace W --track G --kind impl` →
  "what implementation work is ready in track G." `K` resolves to a `task_kind`
  registry id; adds `AND t.kind_id = :kind` to the eligibility query. Tasks with
  `kind_id IS NULL` are excluded only when `--kind` is given. (The registry is
  what makes this filter trustworthy — no typo-fragmented kinds to miss.)
- **Display order: `priority DESC, id ASC`.** This is *presentation only*, not a
  recommendation — priority is surfaced at the top and ties break deterministically
  by creation order so output never jitters between calls. The consumer is free to
  re-sort (e.g. by unblock-impact, which an agent can compute from the DAG itself).

## Reference query

> **Single source of truth for the `next` SQL.** This is the one place the query lives;
> other docs (notably `stx-v3-implementation-brief.md` §4) reference it and describe its
> semantics in prose — they must NOT copy the SQL. Change the query here and nowhere else.

**Eligibility (workspace scope):**

Reads go through the **`live_task` view** (own-task + own-segment + track +
workspace all unarchived) rather than a bare `task t` — a centralized,
defense-in-depth filter so a cascade bug can't leak an orphaned task into the
frontier (see *Defensive visibility* below):

```sql
SELECT t.id, t.title, t.priority, t.status_id, t.segment_id, t.version
FROM live_task t
WHERE t.workspace_id = :ws
  AND t.status_id NOT IN (SELECT id FROM status WHERE workspace_id=:ws AND terminal=1 AND archived=0)
  AND NOT EXISTS (
        SELECT 1 FROM blocks b
        JOIN live_task bt ON bt.id = b.source_task_id
        WHERE b.target_task_id = t.id
          AND b.archived = 0
          AND bt.status_id NOT IN (SELECT id FROM status WHERE workspace_id=:ws AND terminal=1 AND archived=0)
  )
ORDER BY t.priority DESC, t.id ASC;
```

(`t.archived = 0` is folded into the view. The blocker is read through `live_task bt`
too, so BOTH edge liveness — `b.archived = 0` — AND blocker visibility gate: an
orphaned blocker (live task under an archived container, only reachable via a cascade
bug) neither shows nor blocks, consistent with "archived == does-not-exist". In normal
operation this is a no-op — invariant #4 archives a blocker's edges when it is archived,
so `b.archived = 0` already drops it; `live_task` differs only in that degenerate case.
The terminal lookups also exclude archived statuses so a reused name can't shadow a live
non-terminal status.)

**Track scope** is a *flat* filter — no recursive CTE — because every `segment`
carries a denormalized `track_id` (its immutable root anchor). Add a join:

```sql
  JOIN segment f ON f.id = t.segment_id
  ...
  AND f.track_id = :track
```

**Segment-subtree scope** is the one recursive case: walk `parent_segment_id` from
`:segment` down, collect the segment ids, restrict `t.segment_id IN (...)`. Documented
carefully because it is the only scope where the in/out boundary isn't obvious.

### Cross-track blockers (by design)

A task's blockers may live in a different track than the task itself. Track scope
restricts the *returned* tasks to the track, but **not** their blockers — a
cross-story dependency still correctly gates the task. `next --track BILLING` can
therefore return fewer tasks than expected when something in BILLING waits on
AUTH. This is correct (a dependency is a dependency); the deferred inverse
read (`why <task>`) is how a dev would see *what* it's waiting on.

## Performance

At solo-dev scale (hundreds, maybe low-thousands of tasks) this runs in microseconds.
The daemon may simply **recompute on every call** — no incremental frontier
maintenance required day one. Because it is recompute-on-read, `next` is itself
**never stale**; each row carries its `version`, so a consumer can act-then-write
(e.g. move a returned task's status) under optimistic locking and get a clean 409 if
another agent moved first. `ix_blocks_target_live` already indexes the
"what blocks me" lookup. A warm in-memory frontier is a later optimization, not a
requirement.

## Deferred (noted, not built now)

- **Inverse read** (`blocked` / `why <task>`): the same DAG traversal inverted —
  "what unfinished tasks are holding X back." Natural companion to `next`; not in
  this pass.
- **Unblock-impact field**: `next` could optionally annotate each task with the
  count of tasks it would free (transitive `blocks` descendants) for the consumer
  to sort on — without `next` itself ranking. Deferred.
