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
- **Error handling:** **`tech.codingzen:railway:1.1.0`** (package `tech.codingzen.res`)
  — a zero-allocation three-rail `Res<S, F>` result type. The service layer returns
  `Res`, never throws for expected errors. See "Error handling" below; it is the
  basis for §3 invariants, §5 HTTP mapping, §6 write-actor, and §8 tests.

Keep dependencies minimal. Expected deps: http4k core + a server backend, the
SQLite JDBC driver, kotlinx.serialization, kotlinx.coroutines, **railway**
(`tech.codingzen:railway:1.1.0`, zero transitive deps, JVM 21+), **log4j2**
(`org.apache.logging.log4j:log4j-api` + `log4j-core`, plus the `log4j-slf4j2-impl`
bridge so http4k/library SLF4J logs funnel into one config), and a test framework
(kotlin.test / JUnit5). Nothing else unless justified.

- **Logging:** log4j2 is the one logging backend, and it serves two needs from a single
  `log4j2.xml`: (1) traditional app logging — including the §5 `onDefect` stacktrace —
  on the root logger → console (+ optional app file); (2) the **journal** (§7) on a
  dedicated `stx.journal` logger → its own rolling file. This is why log4j2 earns a slot
  in an otherwise minimal dep list: the daemon needs logging regardless, and reusing it
  for the journal removes a hand-rolled file writer.

---

## 1b. Error handling — the railway `Res<S, F>` (read before §3–§8)

All service-layer functions return **`Res<S, F>`** from `tech.codingzen:railway`
(package `tech.codingzen.res`). Three rails:

- **Ok (`S`)** — the success value (a reply DTO / entity).
- **Failure (`F = StxError`)** — an *expected* domain rejection (cycle, illegal
  move, version conflict, not-found). These are values in the type, never thrown.
- **Defect** — an *unexpected* `Throwable` (a bug, an unforeseen JDBC failure).
  Hidden rail; arises only from a thrown exception, never built by hand. Maps to 500.

**The one error type** — a sealed `StxError` is the `F` for every command:

```kotlin
sealed interface StxError {
    data class NotFound(val entity: String, val id: Long) : StxError            // -> 404
    data class Gone(val entity: String, val id: Long) : StxError                // archived -> 410
    data class CycleRejected(val edge: String, val source: Long, val target: Long) : StxError  // blocks-DAG #1 / segment-tree #2 -> 409
    data class CrossWorkspace(val source: Long, val target: Long) : StxError     // invariants #7 (edge endpoints) & #8 (task->status/kind/segment, transition endpoints, segment->parent) -> 409
    data class IllegalTransition(val taskId: Long, val from: Long, val to: Long) : StxError     // no status_transition row -> 409
    data class ImmutableField(val entity: String, val field: String) : StxError // segment.track_id #5 -> 409
    data class Duplicate(val entity: String, val detail: String) : StxError      // live unique-index clash -> 409
    data class VersionConflict(val entity: String, val id: Long, val expected: Int, val actual: Int) : StxError  // OL -> 409
    data class Validation(val message: String) : StxError                        // bad input -> 400
}
```

**How invariants read** — use the `rail { }` builder with `bind()` / `ensure()` /
`raise()`; expected rejections go to Failure, the txn never commits on a non-Ok
(see §6). Example (the `blocks` add — invariants #1 and #7):

```kotlin
fun addBlocks(src: Long, tgt: Long): Res<BlocksRow, StxError> = rail {
    val s = loadLiveTask(src).bind()                                  // NotFound/Gone -> Failure
    val t = loadLiveTask(tgt).bind()
    ensure(s.workspaceId == t.workspaceId) { StxError.CrossWorkspace(src, tgt) }
    ensure(!blocksPathExists(tgt, src)) { StxError.CycleRejected("blocks", src, tgt) }
    blocksRepo.insert(s.workspaceId, src, tgt).bind()                 // Duplicate -> Failure
}
```

**Boundary capture** — adapt throwing JDBC at the edge with `catching`: a known
SQLite constraint becomes a typed `Duplicate` Failure; anything else stays a Defect
(→ 500), never a silent swallow. Do **not** wrap `bind()`/`raise()` in a broad
`catch` — that eats the `RailHalt` short-circuit (catch narrowly or not at all).

This replaces exception-based control flow for *expected* errors. Genuine bugs still
throw → auto-route to Defect → 500; you don't try/catch them in the service layer.

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
- **task_kind** — per-workspace registry of work types (controlled vocabulary,
  same pattern as `status`); referenced by `task.kind_id`. Unlike `status`, the
  registry is **NOT auto-seeded** — it starts EMPTY (kind is optional/nullable, so a
  workspace is usable with zero kinds); the dev registers kinds via `POST /kinds` when
  wanted. Typo-safety comes from the mechanism (only registered kind_ids are settable),
  not from pre-population.
- **task** — the only first-class node. Always attaches to exactly one segment
  (uniform parentage). Has a `status_id`, an optional `kind_id` referencing the
  workspace's `task_kind` registry (NULL=untyped), description, metadata.

Edges (both task↔task):
- **blocks** — the spine; directed, ACYCLIC. Drives `next`.
- **relates_to** — decorative association (free-form `kind`), cyclic OK, never
  affects `next`. Stored directed (source/target) but read as symmetric: "what
  relates to task X" must UNION both directions (X as source OR as target) and **dedup**
  the result. The directed unique index `ux_relates_live(kind, source, target)` is
  intentional — directional kinds like `spawns` (A→B ≠ B→A) must keep both rows — so a
  reciprocal pair for a symmetric kind (`relates-to`/`mentions`) is allowed to exist and
  is collapsed at read time, NOT prevented on write (canonicalizing endpoint order would
  break the directional kinds).

Lifecycle:
- **status** — a task's stage; kanban columns ARE statuses. `terminal=1` means
  "done" (there is NO separate done flag). `kanban_order` is display order only.
- **status_transition** — per-workspace state machine; a move is legal IFF a row
  exists. CYCLES ALLOWED (rework). NO transition guards (legality only).

Everything is **archive-only**: nothing is hard-deleted; `archived=1` hides rows;
FKs never cascade. Ship the verified `stx-v3-schema.sql` as a resource. On-disk version
is tracked via SQLite's `PRAGMA user_version`: a fresh DB (`user_version=0`) loads the
schema whole and stamps `Db.SCHEMA_VERSION`; an existing DB runs the pending forward
migrations (`resources/migrations/NNN_name.sql`) in order, each in its own transaction
that bumps `user_version`. Migrations validate foreign keys with `foreign_key_check`
**inside** that transaction before commit, so a violating migration rolls back atomically
rather than advancing `user_version` past a corrupt state; startup re-checks via
`assertConsistent`. Integer autoincrement PKs.

---

## 3. Daemon-enforced invariants (CRITICAL — these are the service layer's job)

> **Canonical source.** The numbered invariants (and the `next` query in §4, the OL
> rules in §6) are deliberately restated in `stx-v3-schema.sql`, `stx-v3-design.md`, and
> `stx-v3-next.md` for readability. They are the SAME rules — `stx-v3-schema.sql` is the
> authoritative source for data **shape**, this brief for **build** behavior. When you
> change an invariant, the `next` query, or an OL rule, update **every** copy (grep the
> rule's keyword across `docs/`) or they will silently drift.

SQLite enforces FKs and the cheap CHECKs/partial-unique-indexes already in the SQL.
The daemon MUST enforce these nine, transactionally, because SQLite cannot:

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
6. **Container archive cascade.** Archiving a track archives, in the SAME
   transaction, all its live segments and all live tasks under them (each task
   archive cascades its edges via #4). Archiving a **segment** archives, in the
   same transaction, its descendant segments (walk `parent_segment_id` downward)
   and all live tasks under any of them — so a mid-tree segment archive never
   orphans its descendants. A **root** segment is never archived directly (it goes
   only via its track's cascade); reject a direct root-segment archive with
   `StxError.Validation`. Archiving a workspace cascades down through its tracks.
   This is the write-time *integrity* guarantee. (Corollary of #4: archiving an
   incomplete blocker auto-unblocks its dependents — intended.) **Reads do not rely
   on it alone:** list/frontier/kanban queries go through the `live_task` view
   (own-segment + track + workspace unarchived) as defense-in-depth, so a cascade
   bug can't leak an orphan into results. Pair the view with an ASSERTION (see §8) —
   "no live task under an archived container, including an archived ancestor
   segment" — so a bug surfaces instead of being masked. The view stays a flat
   check (own segment only); the recursion for an archived ancestor segment is the
   segment cascade's job, never a recursive read.
7. **Edges never cross a workspace.** Before inserting a `blocks`/`relates_to`
   row, verify source and target tasks share a workspace; reject otherwise. Set
   `edge.workspace_id` from that shared workspace — it is daemon-derived, NEVER
   caller-supplied (do not trust a workspace_id in the request body).
8. **Workspace coherence on every FK write.** The scalar counterpart to #7 —
   SQLite FKs reference a table, not a workspace-scoped subset, so the daemon
   checks same-workspace on each cross-row reference, transactionally:
   - task create/edit: `status_id`, `kind_id` (if non-NULL), and `segment_id` all
     belong to the task's `workspace_id`. (Edit exception: when `clearKind=true` the
     `kind_id` is being cleared, so a passed `kind_id` is not workspace-checked.)
   - task create: `task.workspace_id` is DERIVED from the segment's
     `track.workspace_id` (NEVER caller-supplied — same discipline as #7), so the
     task↔container chain cannot drift.
   - `status_transition` create: `from_status_id` and `to_status_id` both belong
     to the transition's `workspace_id`.
   - segment create: `parent_segment_id` (if set) shares the new segment's
     `track_id` and `workspace_id`.
   Reject a mismatch with `StxError.CrossWorkspace` (mirrors #7). The `live_task`
   view joins both `task.workspace_id` and `segment→track→workspace` but never
   asserts they are equal, so only the daemon closes this hole.
9. **No live task references an archived status or kind.** RESTRICT FKs block only
   DELETE, not archive — archiving a status/kind a live task still points at would
   orphan it. Enforced per axis:
   - **status archive: REJECT** if any live task has that `status_id`
     (`StxError.Validation`, "move those tasks first") — status is load-bearing
     (terminal/`next`/kanban) and `status_id` is NOT NULL, so auto-reassign is unsafe.
     On success also archive its incident `status_transition` rows (`from_status_id`
     or `to_status_id` = it), same txn (like edge cascade #4). Stacks on the existing
     default-status archive reject.
   - **kind archive: NULL-CASCADE** — `UPDATE task SET kind_id=NULL` for every live
     task referencing it (same txn), then archive the kind. kind is optional; `NULL`
     is its natural "untyped" value, so no reject.

All nine live in the service layer, each is small (tens of lines). Test each
explicitly (see §8). Each rejection returns a **typed `StxError` Failure** (§1b) —
`CycleRejected` (#1/#2), `Duplicate`/root-segment clash (#3), `CrossWorkspace`
(#7/#8), `ImmutableField` (#5), `Validation` (root-segment archive #6, default-status
archive, status-archive-while-referenced #9 — see below) — never a thrown exception.
Express them with `ensure(cond) { StxError.X(...) }` inside the command's `rail { }`.

**Plus a bootstrap + default-status rule.** Workspace-create seeds the default status
set (`todo / in-progress / done`, `done.terminal=1`) and transitions (incl.
`done → in-progress`) in the SAME transaction, and sets `is_default=1` on `todo`.
**Exactly one live default status per workspace:** "at most one" is DB-enforced by
`ux_status_one_default` (partial unique index); the daemon provides "at least one" via
the seed. Task-create with no `status_id` lands on the live `is_default=1` status. The
set-default verb clears the old flag and sets the new one in one txn (two UPDATEs —
SQLite checks the partial index per-statement, so clear-then-set has no transient
two-default state). Archiving the current default status is rejected with
`StxError.Validation` ("set another default first"), mirroring the root-segment archive
reject in #6. **The `task_kind` registry is NOT seeded** — it starts empty (kind is
optional/nullable); the dev registers kinds via `POST /kinds` when wanted. Only the
status set is mandatory and seeded.

**Plus a non-invariant write rule:** every mutation sets `updated_at =
datetime('now')` on the touched row. SQLite's `DEFAULT (datetime('now'))` fires
only on INSERT — there is no auto-update — so the daemon owns `updated_at` on
every UPDATE/archive or it silently stays frozen at creation time.

---

## 4. `next` — the frontier (authoritative semantics in stx-v3-next.md)

`next` is a **filter, not a recommender.** It returns the ready set and makes no
prioritization decision. A task is in the frontier IFF:
- `archived = 0`, AND
- its status is NOT terminal, AND
- NO live `blocks` edge points at it from a non-terminal task.

In-progress tasks STAY in the frontier (only terminal/archived/blocked are excluded).
Display order is `priority DESC, id ASC` — **presentation only**, not a recommendation.

**The verified reference SQL lives in `stx-v3-next.md` (Reference query) — that is the
SINGLE SOURCE OF TRUTH for the `next` query** (workspace scope plus the track /
segment-subtree / kind scope additions). Do NOT restate the SQL here; implement it from
next.md so the two never drift.

**Semantics the implementation must preserve** (the *why* behind that SQL):
- **Reads go through the `live_task` view**, not bare `task` — it folds in the defensive
  container-visibility check (own-segment + track + workspace unarchived), centralized so
  every list/frontier/kanban read applies the identical predicate (see §3).
- **Terminal lookups exclude archived statuses** (`terminal=1 AND archived=0`), so an
  archived terminal status can't shadow a live non-terminal one of the same name.
- **The blocker is also read through `live_task`** — so both edge liveness
  (`blocks.archived=0`) AND blocker visibility gate. An orphaned blocker (live task under
  an archived container, only reachable via a cascade bug) neither shows nor blocks,
  consistent with "archived == does-not-exist". Normally a no-op: invariant #4 archives a
  blocker's edges when it is archived, so the edge filter already drops it; the `live_task`
  join differs only in that degenerate case.
- **Order is `priority DESC, id ASC` — presentation only**, never a recommendation.

Scopes (SQL in next.md; conceptually):
- **track:** flat filter via the denormalized `segment.track_id` — no recursive CTE.
- **segment subtree:** the one recursive case — collect segment ids from `:segment` down
  via `parent_segment_id`, then restrict `t.segment_id IN (...)`.
- **kind (orthogonal):** `AND t.kind_id = :kind` (a registry id; NULL-kind tasks are
  excluded when the filter is applied).

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
- `GET  /next?workspace={id}&track={id}&segment={id}&kind={kind_id}&limit={n}` → frontier
- `GET  /workspaces`, `GET /workspaces/{id}/tracks`, `GET /tracks/{id}/segments`
- `GET  /workspaces/{id}/statuses`, `GET /workspaces/{id}/kinds` (registries)
- `GET  /tasks/{id}`, `GET /tracks/{id}/tasks?status={id}` (kanban data)

Mutations (all go through the write-actor):
- `POST /workspaces`                      (create + SEED default statuses/transitions, same txn — see §3 bootstrap)
- `POST /workspaces/{id}/statuses`        (create status)
- `POST /workspaces/{id}/statuses/{sid}/default`  (set the create-time default status —
  clear old `is_default` + set new in one txn; archiving the current default is rejected)
- `POST /workspaces/{id}/kinds`           (create task_kind registry entry)
- `POST /workspaces/{id}/transitions`     (create status transition)
- `POST /workspaces/{id}/tracks`          (create track + auto root segment)
- `POST /tracks/{id}/segments`            (create nested segment)
- `POST /segments/{id}/tasks` or `POST /tracks/{id}/tasks` (create task; the latter
  routes to the track's root segment; `task.workspace_id` is derived from the
  segment's track, NOT taken from the body — invariant #8; status defaults per §3
  bootstrap convention when not given)
- `POST /tasks/{id}/status`   {expected_version,...}  (move status — validate transition exists; CAS on version)
- `PATCH /tasks/{id}`         {expected_version,...}  (edit title/desc/priority/kind_id/metadata; CAS)
- `POST /blocks`  {source,target}          (add blocks edge — DAG-check + same-workspace check; workspace_id derived)
- `POST /relates`  {kind,source,target}    (add relates_to edge — same-workspace check; workspace_id derived)
- `POST /tasks/{id}/archive`, `POST /segments/{id}/archive`, `POST /tracks/{id}/archive`,
  `POST /workspaces/{id}/archive` (archive; container archives cascade per #6 —
  segment archive cascades its subtree; a direct root-segment archive is rejected)
- `POST /workspaces/{id}/statuses/{sid}/archive` (retire a status — invariant #9:
  REJECTED while any live task is in it; on success cascade-archives its incident
  `status_transition` rows; the default status is rejected outright)
- `POST /workspaces/{id}/kinds/{kid}/archive` (retire a kind — invariant #9:
  null-cascades `kind_id=NULL` on referencing live tasks, then archives the kind)

Mutating-existing routes (`PATCH /tasks/{id}`, `POST /tasks/{id}/status`, and the
track/workspace edits) carry **`expected_version`** and are CAS'd — see §6
Optimistic locking. Reads (`GET /tasks/{id}`, etc.) return the row's `version`.

Status moves MUST validate that a matching **live** `status_transition` row exists
(`archived = 0` — the `ux_transition_live` index is already partial on `archived = 0`,
so check liveness, not just existence); an illegal move is an
`StxError.IllegalTransition` Failure. Return JSON for everything, including structured
error bodies.

**The HTTP layer ends every request with a single `fold`** over the service's
`Res` — this is the one place rails become status codes:

```kotlin
service.handle(cmd).fold(
    onOk      = { dto -> Response(OK).json(dto) },            // 200 (creates included; no 201)
    onFailure = { e -> Response(e.httpStatus).json(e.toBody()) },  // 4xx by StxError variant
    onDefect  = { t -> log.error(t); Response(INTERNAL_SERVER_ERROR).json(errBody(t)) }, // 500
)
```

`StxError.httpStatus` maps each variant per §1b (NotFound→404, Gone→410,
Cycle/CrossWorkspace/IllegalTransition/ImmutableField/Duplicate/VersionConflict→409,
Validation→400). Error body is structured JSON: `{ "error": "<variant>", ...fields }`
— `VersionConflict` carries `expected` and `actual` version ints (not the full row), enough
for the agent to detect the clash and re-read. The `onDefect` arm is the only path that logs
a stacktrace; expected failures don't.

Two failures short-circuit **before** the service `fold`: a malformed numeric path/query
param → **400** (a `BadParam` mapped by a `numericGuard` filter at the HTTP edge), and an
unrecognized HTTP verb → **405** (the loopback transport, before routing).

Bulk = a loop of single creates; do NOT build batch endpoints.

---

## 6. Concurrency model

- SQLite opened in **WAL mode** (`PRAGMA journal_mode=WAL;`), foreign keys ON.
- All **mutations** flow through a single **write-actor**: a coroutine draining a
  `Channel` of `(Command, CompletableDeferred<Res<Reply, StxError>>)`, applying each
  in its own transaction, in order. This serializes writes in-process so you never
  contend on the SQLite write lock and command ordering is deterministic.
- **Commit IFF the `Res` is Ok** — this is the load-bearing railway rule. A Failure
  is a *value*, not a throw, so it will NOT auto-roll-back the transaction the way an
  exception would. The actor inspects the result: `Ok → COMMIT`; `Failure → ROLLBACK`
  (a rejected invariant must leave no partial write); `Defect → ROLLBACK + log`. Then
  it completes the `Deferred` with the `Res` (Failure and Defect included — the HTTP
  fold turns them into 4xx/500). Never `getOrThrow()` inside the actor to force a
  rollback; branch on the rail explicitly.
- **Reads** (`next`, queries) run concurrently against the WAL DB; they do not go
  through the write-actor. Each read handler runs in a **deferred read transaction**
  (open a txn, run all its statements, roll back) so a multi-statement read — e.g.
  `GET /tasks/{id}` (task + its edges) or `next --segment` (subtree walk + query) —
  sees ONE WAL snapshot and can't observe a write that commits mid-read.
- This is the entire concurrency design. Do not add locks beyond this.

**Cascade latency (accepted at this scale).** Because all writes are serialized through
the one actor and a container archive cascades in a single transaction (invariant #6 —
every track/segment/task/edge under the container), one big archive (e.g. a workspace
with thousands of tasks) is O(tasks+segments+edges) and **blocks all other writes for
its duration** (reads are unaffected — they run on WAL). At the target scale
(hundreds–low-thousands of tasks) this is sub-millisecond and a non-issue; do NOT
pre-optimize. If it ever bites, the fix is a chunked/incremental cascade — not now.

Notes:
- Every verb is still modeled as a `Command` (§5), but the **read/write split is
  the dispatch boundary**: write Commands are `send`-ed to the actor's Channel and
  the handler awaits the result; read Commands execute inline on the request
  thread against WAL, each inside a rolled-back deferred transaction for a single
  snapshot (above). Decide read-vs-write once, by Command subtype.
- **http4k handlers are blocking.** A write handler bridges to the actor by
  submitting the Command with a `CompletableDeferred<Res<Reply, StxError>>` and
  blocking the request thread on it (`runBlocking`/`.get()`), then `fold`s the
  returned `Res` into a response (§5). That's fine at this scale — just don't expect
  handler suspension to come for free from http4k.

### Optimistic locking (lost-update protection)

The write-actor gives **ordering, not conflict detection**. It cannot see that a
command was computed from a stale read — Agent A reads task v1, Agent B reads v1,
both PATCH; the actor applies both in order and the second silently clobbers the
first. OL closes that hole and is additive to the actor, not redundant.

- Each mutable row (`task`, `track`, `workspace`) has a monotonic `version` int.
  Use `version`, **never `updated_at`** — `datetime('now')` is second-granularity
  (see §3) and collides on sub-second edits.
- Every edit of an EXISTING row is a conditional CAS inside the actor:
  ```sql
  UPDATE task SET <fields>, version = version + 1, updated_at = datetime('now')
   WHERE id = :id AND archived = 0 AND version = :expected_version;
  ```
  `changes()=1` → `ok(newVersion)`. `changes()=0` → re-read and `raise` the right
  Failure: different version → `StxError.VersionConflict` (→ 409, body carries
  `expected`+`actual` version ints so the agent re-reads and re-plans); row missing → `NotFound` (404);
  archived → `Gone` (410). All Failures, not exceptions.
- **Not versioned:** creates (no prior version), the edge tables (append-only;
  their invariants re-validate live against current state, so a stale-based edge is
  caught by the invariant — not OL), and segments (pure filing, not edited).
- A status move is CAS'd on the task, which **doubles as interim work
  coordination**: two agents racing `todo→in-progress` — first wins, the loser gets
  409 and picks another `next` task. It arbitrates the move *instant* only, NOT the
  work duration; reserving a task while an agent works it is the deferred
  claim/lease (§11). OL = correctness of edits; lease = reservation of work —
  different problems, and claim-if-free is itself an OL-style CAS, so no rework.

---

## 7. Journal (log4j2 appender; non-authoritative)

The journal is **not a hand-rolled file writer** — it is a dedicated **log4j2 logger**,
`stx.journal`, with `additivity=false` (so journal lines never leak to console) routed to
its own `RollingFileAppender`. Defined in `log4j2.xml` (§9). `Main` resolves the state dir
and hands it to log4j2 as the `stx.journalDir` system property (set before any logger inits),
so the journal file always sits alongside the DB — `<stateDir>/journal.log` — including the
blank-`XDG_STATE_HOME` case. log4j2 falls back to `${env:XDG_STATE_HOME:-${sys:user.home}/.local/state}/stx`
only for non-`Main` JVMs (tests). `.gitignore`-friendly, throwaway.

On each successful mutation, the write-actor **after commit** builds the event,
serializes it (kotlinx.serialization), and calls `journal.info(json)` — one **JSON line**
per event:
- SQLite remains the source of truth; the journal is **NEVER read back** to determine
  state (it is write-only — nothing in the daemon opens it for reading).
- Each event: a high-resolution timestamp, `workspace` id, entity type+id, verb, and the
  post-mutation `version` (where the entity is versioned). **No `seq` field** — see below.
- Global file with a `workspace` field per event (not per-workspace files). Note: events
  built from an `IdReply` (archives, set-default) currently emit `workspaceId=null` — the
  reply carries only entity+id — so the `workspace` field is populated best-effort, not
  universally.
- **Ordering comes for free, no seq needed.** Only the write-actor emits to `stx.journal`
  — one serialized coroutine, logging after commit in commit order — so the physical line
  order in the file *is* the event order (rotation preserves it: read older segments
  first). The timestamp covers human reading and rough cross-run ordering. A `seq` field
  would only matter as a *cursor* for a programmatic consumer, and there is none.
- **Best-effort, cannot affect the txn.** log4j2 swallows appender errors by default, and
  the call happens after commit — so a journal-write failure can never roll back or
  corrupt the DB transaction. This property is inherent, not something we hand-code.
- Rotation/retention is the `RollingFileAppender`'s job (size/time policy in `log4j2.xml`).

**Deferred — durable cursor (the only kind of `seq` worth having).** A future
subscription/notification channel needs a restart-surviving, monotonic cursor. A
run-scoped counter would be useless (resets each run, collides across runs) and a
byte-offset/line cursor breaks across rotation — so when that consumer lands, add a
one-row SQLite `meta(key,value)` counter bumped *in the mutation txn* and stamp it onto
the event. That is the day `seq` earns its place. Do NOT build it now; the journal today
is human/observability output (`tail -f journal.log`), not a programmatic feed.

---

## 8. Tests (write these — they encode the invariants)

Use the verified scenarios from our design work as the test backbone. **"Rejected"
below means the service returns a Failure** — assert `res.isFailure` and that
`res.failureOrNull()` is the expected `StxError` variant (e.g.
`is StxError.CycleRejected`), NOT `assertThrows`. A bug surfaces as a Defect: assert
with `res.defectOrNull()` where you mean "unexpected throwable." Reserve thrown-
exception assertions for genuinely exceptional paths only.

Schema/invariant tests:
- self-block rejected; duplicate LIVE blocks edge rejected; archive-then-recreate
  the same edge ALLOWED (partial unique index); duplicate live status name rejected;
  self-transition rejected; bad-FK insert rejected.
- migrations: a registered forward migration applies and bumps `user_version`; a missing
  registration in the chain is refused; a downgrade is refused; a migration that leaves an
  FK violation rolls back atomically (`user_version` does NOT advance, its rows are gone).
- blocks DAG: inserting an edge that would create a cycle is rejected.
- segment tree: setting a parent that creates a cycle is rejected.
- exactly one root segment per track (second root rejected).
- archiving a task archives its incident blocks/relates_to rows.
- cross-workspace edge rejected (blocks AND relates_to whose endpoints live in
  different workspaces).
- workspace coherence (#8) rejected: task create/edit pointing at a status, kind, or
  segment from ANOTHER workspace → `CrossWorkspace`; a transition whose from/to
  statuses span workspaces → `CrossWorkspace`; a segment whose `parent_segment_id`
  lives in another track/workspace → `CrossWorkspace`. Sanity: task create DERIVES
  `workspace_id` from the segment (a mismatched body `workspace_id` is ignored, not
  trusted).
- bootstrap: a freshly created workspace already has the seeded statuses +
  transitions, with exactly one `is_default=1` status, and a task can be created in it
  immediately (with no `status_id`, it lands on the live default status).
- default-status flag: a second `is_default=1` in the same workspace is rejected by
  `ux_status_one_default`; the set-default verb moves the flag atomically (old clears,
  new sets, one survives); archiving the current default status is rejected
  (`Validation`); after set-default, a no-status task-create lands on the NEW default.
- container archive cascade: archiving a track archives its segments + tasks (+
  their edges); archiving a workspace cascades down; archiving a non-root SEGMENT
  archives its descendant segments + their tasks (+ edges); a direct ROOT-segment
  archive is rejected (`Validation`); no live task remains under an archived
  container, and `next` returns none of them.
- status/kind archival (#9): archiving a status while a live task is in it is rejected
  (`Validation`); after the task moves off it, archive succeeds AND its incident
  `status_transition` rows (from_/to_ = it) are archived in the same txn; archiving the
  default status is rejected. Archiving a kind null-cascades — referencing live tasks get
  `kind_id=NULL` and the kind is archived; a consistency assertion confirms no live task
  references an archived status or kind.
- defensive visibility: `next`/kanban read through `live_task`. Force the orphan
  case — set a track `archived=1` WITHOUT cascading its tasks (direct DB write) —
  and assert `next` still returns none of those tasks (the view masks it). Then a
  separate consistency-assertion test FINDS that orphan ("no live task under an
  archived container, including an archived ANCESTOR segment") so the bug surfaces
  rather than hides.
- `next` query trio (consistency):
  - #7 archived terminal status: archive a terminal status and create a live
    non-terminal status REUSING its name; a task in that live status is treated as
    non-terminal (the archived terminal row does NOT count) and appears in `next`.
  - #5 orphan blocker: blocker task live but its container archived (direct DB write,
    no edge cascade) → its dependent is NOT gated (appears in `next`), since the blocker
    is read through `live_task`; the existing consistency assertion still finds the
    orphan. Sanity: a NORMALLY-archived blocker (edges cascaded via #4) also drops out —
    same result, proving the `live_task` join only matters in the orphan case.
  - #6 relates_to symmetry: insert reciprocal `relates-to` rows A→B and B→A; "what
    relates to A" UNIONs both directions and returns B exactly once (deduped). A
    directional `spawns` A→B and B→A stay distinct (both readable, not collapsed).

Optimistic-locking tests:
- two PATCHes with the same `expected_version`: the first bumps `version`; the
  second is rejected 409 and the body carries the current row.
- status move with a stale `expected_version` rejected (409); with the current
  version accepted.
- two agents race the same `todo→in-progress` move: exactly one wins, the other
  409s (interim first-mover-wins).
- create succeeds with no `expected_version`.
- an edge add computed from a stale read is caught by its invariant (DAG /
  same-workspace), NOT by OL — sanity that edges are correctly un-versioned.

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
- illegal status move → `StxError.IllegalTransition` Failure → 409; legal move → Ok.
- the `fold` mapping: each `StxError` variant produces its mapped status code and a
  structured JSON body (NotFound→404, Gone→410, VersionConflict→409 with current row,
  Validation→400); a forced Defect (throw in a handler) → 500 with a logged stacktrace
  and no leak of internal detail in the body.
- edge cases that must NOT be 500s: a malformed numeric path/query param (e.g.
  `/tasks/abc`, `/next?track=x`) → 400; an unrecognized HTTP verb → 405.
- server binds to 127.0.0.1 only.

---

## 9. Suggested package layout

```
stx/
  build.gradle.kts
  src/main/resources/schema.sql        # = stx-v3-schema.sql verbatim
  src/main/resources/log4j2.xml        # root logger (app/console) + stx.journal appender
  src/main/kotlin/stx/
    Main.kt                            # parse args, open DB (WAL), start actor + http4k
    transport/
      HttpApi.kt                       # http4k routes -> parse to Command -> service
      Json.kt                          # kotlinx.serialization setup
    command/
      Command.kt                       # sealed interface + data classes (the protocol)
    error/
      StxError.kt                      # sealed StxError (the F type) + httpStatus + toBody
    service/
      Service.kt                       # exhaustive when(command) -> Res<Reply, StxError>; the 9 invariants
      WriteActor.kt                    # single coroutine draining the Command Channel; commit IFF Ok
      Frontier.kt                      # next() logic / query building
      Invariants.kt                    # DAG check, segment-tree check, cascade, etc. (rail/ensure)
    repo/
      Db.kt                            # JDBC connection, WAL pragma, schema init
      TaskRepo.kt, TrackRepo.kt, ...   # thin hand-written-SQL repos (return Res; catching at the JDBC edge)
    log/
      Journal.kt                       # thin: serialize event -> `stx.journal` log4j2 logger (after commit)
  src/test/kotlin/stx/                 # the tests from §8
```

---

## 10. Build order (suggested for Claude Code)

1. `build.gradle.kts` + project skeleton (incl. `tech.codingzen:railway:1.1.0`);
   get it compiling with a hello route.
2. `Db.kt`: open SQLite WAL, run `schema.sql`, FK pragma on. Smoke-test it loads.
3. `Command.kt` + `StxError.kt`: the sealed command hierarchy (§5) and the sealed
   `StxError` (§1b) with `httpStatus`/`toBody`. Settle the `Res<Reply, StxError>`
   service signature before writing handlers.
4. Repositories: hand-written SQL returning `Res`; `catching` known SQLite
   constraints into typed Failures at the JDBC edge.
5. `Invariants.kt` + `Service.kt`: the exhaustive `when` dispatch returning `Res`,
   plus the 9 invariants (rail/ensure → typed Failures), each with a unit test (§8).
   Workspace-create seeds the default status set + transitions in the same txn and
   sets `is_default=1` on `todo` (§3 bootstrap); task-create derives `workspace_id`
   from the segment and, when no `status_id` is given, uses the live `is_default`
   status.
6. `Frontier.kt`: implement `next` with the §4 query; write the lifecycle + rework
   test and make it pass.
7. `WriteActor.kt`: route all mutations through the single coroutine; commit IFF the
   `Res` is Ok, roll back on Failure/Defect, complete the `Deferred` with the `Res`.
8. `HttpApi.kt`: the lightly-RESTful façade, 127.0.0.1 only; wire routes to Service
   and end each with the single `fold` → status code + JSON body (§5).
9. `Journal.kt` + `log4j2.xml`: journal via the `stx.journal` log4j2 appender — serialize
   and emit one JSON line per successful mutation (after commit, best-effort).
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
- **Assignees/users, recurring tasks, deadline-driven scheduling** — no date columns; if ever
  needed, dates live in `metadata_json`. `next` must NOT become time-aware.
- **Incremental frontier caching** (recompute on read).
- **TUI**, notifications/subscriptions, analytics/velocity reads — later, not now.
- **Transition guards** (status transitions are legality-only; gates are honored by
  the dev/agent, not enforced).
- **Auth / non-loopback binding / batch endpoints / gRPC / Spring / ORM.**
