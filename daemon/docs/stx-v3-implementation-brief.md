# stx v3.0.0 — Implementation Brief for Claude Code

This is a build spec for a greenfield Kotlin implementation of **stx**, a local
daemon that stores and serves a developer's work items for themselves and their
local agents. Build it to this spec. The companion files `stx-v3-schema.sql`,
`stx-v3-design.md`, and `stx-v3-next.md` are the authoritative data-model and
semantics references; this brief is the authoritative *implementation* reference.
Where they conflict on data shape, the schema SQL wins; where they conflict on
build/stack, this brief wins.

---

## 0. What stx is (context for every decision)

stx is a **datastore + frontier server for agent sessions**, run locally on a dev
machine. The developer curates structure; the dev and local agents read it as a
tool. It is NOT a JIRA replacement and stores no team/multi-user concepts. The bar
is "faster and more structured than a TODO.md," not high throughput — a single dev
plus a few local agents, hundreds to low-thousands of tasks. Do not over-engineer
for scale.

Core philosophy that should shape the code:
- **The store is self-defending.** Invariants are enforced (some in SQLite, some in
  the daemon) so that an agent writing to it cannot corrupt it.
- **Single writer.** One daemon owns all writes; this is what keeps things simple.
- **Recompute on read.** `next` is cheap to recompute; do not build incremental
  caching. Correctness (esp. for rework) beats premature optimization.

---

## 1. Stack (do NOT deviate without reason)

- **Language:** Kotlin (latest stable), targeting a recent stable JDK (21+).
- **Build:** Gradle with Kotlin DSL (`build.gradle.kts`).
- **HTTP server:** **http4k** bound to `127.0.0.1` ONLY (never `0.0.0.0`).
- **JSON:** **kotlinx.serialization**.
- **Persistence:** **plain JDBC + SQLite** (the `xerial/sqlite-jdbc` driver),
  **WAL mode**. NO ORM (no Hibernate/JPA/Exposed). Hand-written SQL in a thin
  repository layer.
- **Concurrency:** Kotlin coroutines. A single **write-actor** coroutine serializes
  all mutations; reads run concurrently against WAL.
- **NO Spring, NO gRPC, NO DI framework, NO auth.** Loopback-only binding is the
  entire security model (single-user local box; accept that any local process can
  reach it — same as any dev server).

Keep dependencies minimal. Expected deps: http4k core + a server backend, the
SQLite JDBC driver, kotlinx.serialization, kotlinx.coroutines, and a test framework
(kotlin.test / JUnit5). Nothing else unless justified.

---

## 2. Data model (authoritative shape in stx-v3-schema.sql)

Hierarchy: **workspace → track → segment\* → task**

- **workspace** — top-level environment and edge boundary. Edges never cross it.
- **track** — root-only anchor (NEVER nests, no parent). One coherent line of work.
  Carries description + metadata (the track "blurb").
- **segment** — nestable filing node under a track. PURE FILING: no metadata, no
  context, no inheritance. `parent_segment_id` forms a tree; NULL = directly under
  the track (a root segment). Has denormalized immutable `track_id` for flat
  track-scoped queries. Each track has exactly ONE root segment (`is_root=1`).
- **task** — the only first-class node. Always attaches to exactly one segment
  (uniform parentage). Has a `status_id`, an optional single-valued `kind`
  (impl/review/research/…, free text, NULL=untyped), description, metadata.

Edges (both task↔task):
- **blocks** — the spine; directed, ACYCLIC. Drives `next`.
- **relates_to** — decorative association (free-form `kind`), cyclic OK, never
  affects `next`.

Lifecycle:
- **status** — a task's stage; kanban columns ARE statuses. `terminal=1` means
  "done" (there is NO separate done flag). `kanban_order` is display order only.
- **status_transition** — per-workspace state machine; a move is legal IFF a row
  exists. CYCLES ALLOWED (rework). NO transition guards (legality only).

Everything is **archive-only**: nothing is hard-deleted; `archived=1` hides rows;
FKs never cascade. Use the verified `stx-v3-schema.sql` verbatim as the schema-init
script (ship it as a resource, execute on first run / if tables absent). Integer
autoincrement PKs.

---

## 3. Daemon-enforced invariants (CRITICAL — these are the service layer's job)

SQLite enforces FKs and the cheap CHECKs/partial-unique-indexes already in the SQL.
The daemon MUST enforce these five, transactionally, because SQLite cannot:

1. **blocks is a DAG.** Before inserting a blocks edge (source→target), verify no
   path already exists target→…→source (a DFS/BFS over live blocks edges). Reject
   with a clear error if it would create a cycle. Self-edges already blocked by CHECK.
2. **segment tree is acyclic within a track.** Before setting `parent_segment_id`,
   verify the new parent is not a descendant of the segment. Reject cycles.
3. **exactly one root segment per track.** On track creation, auto-create its root
   segment (`is_root=1`, `parent_segment_id=NULL`). The partial unique index backs
   this up; the daemon is responsible for creating it.
4. **archive cascade for edges.** When a task is archived, archive (set archived=1)
   all incident `blocks` and `relates_to` rows in the SAME transaction. This keeps
   the invariant "a live edge always connects two live tasks," which is what lets
   `next` skip checking blocker archived-state.
5. **segment.track_id is immutable** and equals its root ancestor's track. Never let
   a segment move between tracks; never let `track_id` be updated.

All five live in the service layer, each is small (tens of lines). Test each
explicitly (see §8).

---

## 4. `next` — the frontier (authoritative semantics in stx-v3-next.md)

`next` is a **filter, not a recommender.** It returns the ready set and makes no
prioritization decision. A task is in the frontier IFF:
- `archived = 0`, AND
- its status is NOT terminal, AND
- NO live `blocks` edge points at it from a non-terminal task.

In-progress tasks STAY in the frontier (only terminal/archived/blocked are excluded).
Display order is `priority DESC, id ASC` — **presentation only**, not a recommendation.

**Verified reference query (workspace scope)** — use this exact logic:

```sql
SELECT t.id, t.title, t.priority, t.status_id, t.kind, t.segment_id
FROM task t
WHERE t.workspace_id = :ws
  AND t.archived = 0
  AND t.status_id NOT IN (SELECT id FROM status WHERE workspace_id=:ws AND terminal=1)
  AND NOT EXISTS (
        SELECT 1 FROM blocks b
        JOIN task bt ON bt.id = b.source_task_id
        WHERE b.target_task_id = t.id
          AND b.archived = 0
          AND bt.status_id NOT IN (SELECT id FROM status WHERE workspace_id=:ws AND terminal=1)
  )
ORDER BY t.priority DESC, t.id ASC;
```

Scopes (all add to the above):
- **track:** `JOIN segment s ON s.id=t.segment_id ... AND s.track_id = :track`
  (flat filter — no recursive CTE, thanks to denormalized segment.track_id).
- **segment subtree:** recursively collect segment ids from :segment down via
  `parent_segment_id`, then `t.segment_id IN (...)`.
- **kind (orthogonal):** `AND t.kind = :kind`.

Workspace scope is always required; track/segment/kind are optional filters.

Cross-track blockers are intentional: a task's blocker may live in another track and
still gates it. Track scope restricts returned tasks, NOT their blockers.

---

## 5. Command protocol & HTTP surface

Internally, model the full API as a Kotlin **sealed interface `Command`** with a
`data class` per verb. Dispatch via an **exhaustive `when`** (no else branch — the
compiler must force handling of every command; this is a deliberate safety feature
for when new verbs are added). Serialize with kotlinx.serialization.

The HTTP layer is a thin, lightly-RESTful **façade** that parses a request into the
right `Command` and hands it to the service layer. Keep the routes curl-friendly so
generic tools can poke the daemon. Suggested routes (adjust naming sensibly):

Reads:
- `GET  /next?workspace={id}&track={id}&segment={id}&kind={k}&limit={n}` → frontier
- `GET  /workspaces`, `GET /workspaces/{id}/tracks`, `GET /tracks/{id}/segments`
- `GET  /tasks/{id}`, `GET /tracks/{id}/tasks?status={id}` (kanban data)

Mutations (all go through the write-actor):
- `POST /workspaces`                      (create)
- `POST /workspaces/{id}/statuses`        (create status)
- `POST /workspaces/{id}/transitions`     (create status transition)
- `POST /workspaces/{id}/tracks`          (create track + auto root segment)
- `POST /tracks/{id}/segments`            (create nested segment)
- `POST /segments/{id}/tasks` or `POST /tracks/{id}/tasks` (create task; the latter
  routes to the track's root segment)
- `POST /tasks/{id}/status`               (move status — validate transition exists)
- `PATCH /tasks/{id}`                      (edit title/desc/priority/kind/metadata/dates)
- `POST /blocks`  {source,target}          (add blocks edge — DAG-check)
- `POST /relates`  {kind,source,target}    (add relates_to edge)
- `POST /tasks/{id}/archive`, `POST /tracks/{id}/archive`, etc. (archive; cascade edges)

Status moves MUST validate that a matching `status_transition` row exists; reject
illegal moves with a clear 4xx and message. Return JSON for everything, including
structured error bodies.

Bulk = a loop of single creates; do NOT build batch endpoints.

---

## 6. Concurrency model

- SQLite opened in **WAL mode** (`PRAGMA journal_mode=WAL;`), foreign keys ON.
- All **mutations** flow through a single **write-actor**: a coroutine draining a
  `Channel<Command>` (or equivalent), applying each in its own transaction, in order.
  This serializes writes in-process so you never contend on the SQLite write lock
  and command ordering is deterministic.
- **Reads** (`next`, queries) run directly/concurrently against the WAL DB; they do
  not go through the write-actor.
- This is the entire concurrency design. Do not add locks beyond this.

---

## 7. Sidecar event log (lightweight; non-authoritative)

On each successful mutation, the write-actor appends one event to a **sidecar log**:
- Append-only file in the XDG state dir (e.g. `$XDG_STATE_HOME/stx/events.log`),
  `.gitignore`-friendly, throwaway. SQLite remains the source of truth; the log is
  NEVER read back to determine state.
- Each event: a **monotonic seq number** (in-process counter, persisted enough to
  resume), timestamp, `workspace` id, entity type+id, verb, and a small payload.
- Global log with a `workspace` field (not per-workspace files).
- Keep this simple and isolated; it must be impossible for a log-write failure to
  corrupt or roll back the actual DB transaction (log after commit, best-effort).

This log is intentionally minimal now; a future subscription/notification channel
may build on the seq numbers, but do not build that yet.

---

## 8. Tests (write these — they encode the invariants)

Use the verified scenarios from our design work as the test backbone:

Schema/invariant tests:
- self-block rejected; duplicate LIVE blocks edge rejected; archive-then-recreate
  the same edge ALLOWED (partial unique index); duplicate live status name rejected;
  self-transition rejected; bad-FK insert rejected.
- blocks DAG: inserting an edge that would create a cycle is rejected.
- segment tree: setting a parent that creates a cycle is rejected.
- exactly one root segment per track (second root rejected).
- archiving a task archives its incident blocks/relates_to rows.

`next` lifecycle test (the key behavioral test):
- Build a chain T1→T2→T3→T4→T5 via blocks, plus a cross-track dependency.
- Frontier starts as {T1}; completing tasks walks the frontier forward.
- In-progress tasks remain in the frontier (only terminal removes them).
- **Rework:** moving a terminal task back to a non-terminal status correctly drops
  its dependents OUT of the frontier again (this is why recompute-on-read matters —
  test it explicitly).
- Track-scoped `next` returns only that track's tasks but still respects
  cross-track blockers.
- `--kind` filter restricts correctly and excludes NULL-kind tasks when applied.

HTTP/protocol tests:
- the `when` dispatch is exhaustive (compile-time, but assert round-trip serialization
  of every Command).
- illegal status move rejected with 4xx; legal move accepted.
- server binds to 127.0.0.1 only.

---

## 9. Suggested package layout

```
stx/
  build.gradle.kts
  src/main/resources/schema.sql        # = stx-v3-schema.sql verbatim
  src/main/kotlin/stx/
    Main.kt                            # parse args, open DB (WAL), start actor + http4k
    transport/
      HttpApi.kt                       # http4k routes -> parse to Command -> service
      Json.kt                          # kotlinx.serialization setup
    command/
      Command.kt                       # sealed interface + data classes (the protocol)
    service/
      Service.kt                       # exhaustive when(command); holds the 5 invariants
      WriteActor.kt                    # single coroutine draining Channel<Command>
      Frontier.kt                      # next() logic / query building
      Invariants.kt                    # DAG check, segment-tree check, cascade, etc.
    repo/
      Db.kt                            # JDBC connection, WAL pragma, schema init
      TaskRepo.kt, TrackRepo.kt, ...   # thin hand-written-SQL repositories
    log/
      Sidecar.kt                       # append-only seq-numbered event log
  src/test/kotlin/stx/                 # the tests from §8
```

---

## 10. Build order (suggested for Claude Code)

1. `build.gradle.kts` + project skeleton; get it compiling with a hello route.
2. `Db.kt`: open SQLite WAL, run `schema.sql`, FK pragma on. Smoke-test it loads.
3. `Command.kt`: the sealed hierarchy for all verbs in §5.
4. Repositories: hand-written SQL for create/read/update/archive per entity.
5. `Invariants.kt` + `Service.kt`: the exhaustive dispatch + the 5 invariants, each
   with a unit test (§8) as you go.
6. `Frontier.kt`: implement `next` with the §4 query; write the lifecycle + rework
   test and make it pass.
7. `WriteActor.kt`: route all mutations through the single coroutine.
8. `HttpApi.kt`: the lightly-RESTful façade, 127.0.0.1 only; wire routes to Service.
9. `Sidecar.kt`: append-only seq log on successful mutations (after commit).
10. Fill remaining verbs/routes against the established pattern; finish the test suite.

Deliver something runnable early (steps 1–2), then build outward. Prefer many small
verified steps over a big-bang implementation. When adding any new Command, let the
exhaustive `when` force you to handle it everywhere.

---

## 11. Explicitly OUT of scope (do not build)

- **Agent claim/lease** (claimed_by/claimed_until + atomic claim-if-free). Designed
  but DEFERRED. Add only when a second concurrent agent actually runs. It will be two
  nullable columns + one atomic primitive; the agent framework owns TTL/heartbeat/
  release policy, not stx. Leave room, build nothing now.
- **Labels/tags.** Rejected by design. `task.kind` covers the one real axis.
- **General hierarchy on tasks** (no parent_task / subtasks — use segments + blocks).
- **Assignees/users, recurring tasks, deadline-driven scheduling** (due_date is
  stored metadata only; `next` must NOT become time-aware).
- **Incremental frontier caching** (recompute on read).
- **TUI**, notifications/subscriptions, analytics/velocity reads — later, not now.
- **Transition guards** (status transitions are legality-only; gates are honored by
  the dev/agent, not enforced).
- **Auth / non-loopback binding / batch endpoints / gRPC / Spring / ORM.**
