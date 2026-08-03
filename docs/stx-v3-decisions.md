# stx v3.0.0 — Implementation Decisions

Resolutions for points the four authoritative docs leave open or under-specified.
These bind the build; they do not override the schema/next/brief on anything they
already state. Recorded here (rather than scattered across the prose docs) to avoid
the cross-doc drift the brief warns about.

## D1 — Invariant count is 9
Canonical count is **nine** (numbered 1–9 in schema.sql, design.md, brief §3). Stale
"seven"/"eight" mentions were corrected in design.md and brief §3 / §9.

## D2 — Reading a task's edges
The brief §5 exposes no route to read a task's `blocks` / `relates_to` edges, but §8
tests require it. Resolution: **`GET /tasks/{id}` embeds edges in its response DTO**:
- `blocks`: incoming (tasks that block this) and outgoing (tasks this blocks), live edges only.
- `relates_to`: the symmetric read — UNION both directions (X as source OR target),
  **deduped** for symmetric kinds; directional kinds (`spawns`) keep both rows distinct.
No new routes. The *transitive* inverse read is D8's `blockers` — this one-hop view is its depth-1
slice, and the two must agree.

## D3 — Seeded status transitions (workspace bootstrap)
The seed uses a four-stage machine `Backlog / Implementation / Review / Done` (`Done`
terminal, `Backlog` default). Reaching a terminal status is always legal regardless of
edges (the `stx done` escape hatch — see `moveStatus`), so no direct `→Done` edge is
seeded from `Backlog`/`Implementation`. Seed exactly this set in the same txn as the
status seed (`StxService.createWorkspace`):
- `Backlog → Implementation`
- `Implementation → Review`
- `Review → Done`
- `Implementation → Backlog`   (rework back-edge)
- `Review → Implementation`    (rework back-edge)
- `Done → Review`              (rework back-edge)

## D4 — Direct GET of an archived row
Reconciles the schema note (a direct `GET /tasks/{id}` may bypass `live_task` to inspect
an archived row on purpose) with the brief's `Gone → 410`:
- **`GET /tasks/{id}`** (single, direct): returns **200** + the row even when archived,
  with an `archived` boolean in the DTO. It bypasses `live_task` deliberately.
- **List / `next` / kanban reads**: go through `live_task`; archived rows never appear.
- **Mutations** targeting an archived row: **410 `Gone`** (`StxError.Gone`).

## D5 — Pinned versions / toolchain
Verified locally available: JDK 21.0.6 (Temurin), Gradle 9.3.1, kotlinc, sqlite3 3.45.
- Kotlin **2.3.0** (matches `railway`'s `kotlin-stdlib`).
- JDK toolchain **21**.
- `tech.codingzen:railway:1.1.0` (Maven Central; package `tech.codingzen.res`).
- http4k, **SunHttp** server backend (loopback, no extra server dep).
- `org.xerial:sqlite-jdbc` latest 3.x.
- `org.jetbrains.kotlinx:kotlinx-serialization-json`.
- `org.jetbrains.kotlinx:kotlinx-coroutines-core`.

Exact pinned versions live in `gradle/libs.versions.toml` (the version-catalog source of
truth) — Kotlin 2.3, http4k 6.54.x, serialization/coroutines 1.11.x as of 3.0.0. This list
names the dependencies; the catalog owns the numbers.
- log4j2 2.23+ (`log4j-api` + `log4j-core` + `log4j-slf4j2-impl`).
- Test: `kotlin-test-junit5` + JUnit 5.

## D6 — relates_to.kind stays free text
`relates_to.kind` is intentionally left as unconstrained `TEXT` (`schema.sql:206`) — **no CHECK, no
registry, no enum**. stx is a developer tool for power users, and an open taxonomy is a feature: the
set of useful relation kinds (`spawns`, `mentions`, `relates-to`, and whatever a user coins) is
open-ended and evolves per-user, not per-schema.

Considered and rejected:
- **A per-workspace registry table** (the `task_kind` / `status` pattern). Rejected: relation kinds
  read as a *cross-workspace* taxonomy, so per-workspace vocab would force re-registration or drift
  across workspaces; and the read layer already **owns** kind semantics (symmetric UNION+dedup vs
  directional `spawns`, D2), so an extensible registry would need a `symmetric` flag the read path
  consults — cost without payoff for the target user.
- **A config-file allowed-values list.** Rejected: no config subsystem exists (settings are env vars
  + hardcoded defaults); this would mean inventing one just to constrain a field we chose not to
  constrain.

Mitigation for the one real downside (typo drift, e.g. `relates-to` vs `relates_to`): a **read-only**
`stx relate-kinds -w <ws>` (`GET /workspaces/{id}/relates-kinds`) lists the distinct `kind` values in
live use, so a user can self-check without a hard constraint. It reports drift; it does not prevent it.

## D7 — Reciprocal relates_to rows are stored as-is; the daemon does NOT dedup them
`ux_relates_live` is on the **ordered** triple `(kind, source_task_id, target_task_id)`
(`schema.sql`), so a reciprocal pair — `(relates-to, A→B)` and `(relates-to, B→A)` — persists as **two
live rows**. This is **intended, not a bug**: for a *symmetric* kind they are the same fact, but for a
*directional* kind (`spawns A→B` ≠ `spawns B→A`, D2 tracks `outgoing`) they are distinct, and because
`kind` is free text (D6) the daemon **cannot know which kinds are symmetric** — so it stores exactly
what it was told and stays dumb.

Consequence, deliberately accepted: reads are **not uniformly deduped**. `GET /tasks/{id}` dedups from
that one task's vantage (`distinctBy { kind to otherTaskId }`, D2), but the **bulk** edge read
`GET /workspaces/{id}/edges` (`RelatesRepo.liveByWorkspace`, backing `stx graph`) returns the raw
rows — so a symmetric relation appears as two edges there.

Considered and rejected:
- **Canonicalize on write** (`min→max`): destroys direction for directional kinds. Rejected.
- **Symmetric unique index / per-kind symmetry flag**: needs a kind registry, which D6 killed.
- **Dedup the bulk read in the daemon**: would collapse `(kind, {s,t})` unordered, losing direction
  for directional kinds, and pushes presentation policy into the write-actor's read path.

Resolution: **keep the daemon dumb.** Storage is directional and honest; collapsing symmetric
relations to a single (typically undirected) edge is the **renderer's** job — e.g. graphviz
`concentrate=true`, or drawing relates_to undirected — decided at view time where kind-symmetry
intent actually lives. Do not "fix" the un-deduped bulk read; it is deduping-free on purpose.

## D8 — `blockers` is a daemon endpoint, not a client-side traversal
The inverse read (`stx blockers <id>` → `GET /tasks/{id}/blockers`) walks `blocks` **backward** from a task
and returns the unfinished work holding it back, transitively. It was deferred in next.md; this
records how it was built.

It could have been assembled client-side from `GET /workspaces/{id}/edges` + per-track task reads —
`stx graph` already does exactly that. Three reasons it wasn't:

1. **Snapshot integrity.** `HttpApi.read()` exists so a multi-statement read shares one WAL
   snapshot. A client-side walk would be edges at T1 + tasks at T2 + statuses at T3, with the write
   actor committing in between — it could report a blocker that was finished mid-traversal.
   Answering a question about *live gating state* from a torn read is the one thing this must not do.
2. **One predicate, not two.** `blockers` is the exact inverse of `next`, so its eligibility rule must be
   *the same rule* — `live_task` ∧ non-terminal ∧ `blocks.archived=0`. A Go reimplementation would be
   a second frontier semantics with nothing tying the two together. `service/Blockers.kt` is a
   deliberate sibling of `service/Frontier.kt` for that reason.
3. **Cost shape.** Client-side is O(tracks) round trips and pulls every task in the workspace to
   answer a question about a handful; daemon-side is one request on `ix_blocks_target_live`, the
   index next.md already names for this walk.

**Semantics.** The walk passes only *through* live, non-terminal blockers on unarchived edges — a
done blocker no longer gates, so what gated *it* is irrelevant. `blocks` is a DAG (invariant #1) so
there are no cycles, but diamonds are real: a shared blocker is reported **once, at its minimum
depth**. A `maxDepth` cap (default 64, `?depth=`) is bound into the CTE as defense-in-depth — it can
only bite if invariant #1 is broken. An archived or terminal target returns an empty list, not an
error; an unknown id is `NotFound`.

Two boundaries are enforced in `StxService.listBlockers`, **not** in the CTE, so `Blockers.list`
stays a clean inverse of Frontier's *blocker* predicate:

- **The target's own status/archived state.** The CTE filters the blockers, never the task being
  asked about — so a Done task would otherwise report the blockers it had while open, and the
  identity below would break at the terminal boundary. Frontier applies the same status test to its
  candidate rows; this restores the symmetry. Checking `archived` explicitly also means an archived
  target is empty on its own terms rather than only because cascade #4 removed its edges.
- **`maxDepth >= 1`.** The CTE's base case is unconditional and only the recursive step reads the
  cap, so 0 or a negative value would silently behave as 1. It is a `Validation` error instead.

**Naming.** next.md and design.md both floated `why <task>` (and `blocked`) for this. Neither
survived: `why` is a question word that says nothing about what comes back, and `blocked` /
`blocked-by` inverts under a command name — `stx blocked-by 42` parses as "what is blocked *by* 42",
which is the outgoing edge, the opposite of this read. `blockers` is a plural noun naming exactly
what the rows are, with no direction ambiguity.

**The identity this buys** (asserted in `BlockersTest`): a live non-terminal task is in `next` **iff**
its blocker list is empty. That makes `blockers` provably the inverse read rather than merely some traversal,
and it ties D2's one-hop `blocked-by` view to `blockers --depth 1`.

**Presentation.** The CLI renders a *depth-layered list, not a spanning tree* — indentation is
minimum hop count, and the diamond's shared node appears once. `stx blockers -q` prints the **blocker**
ids (not the queried id), which is what makes `stx blockers 42 -q | stx done -` work; empty is exit 1 per
the grep convention, so `if stx blockers 42 -q >/dev/null` reads as "is it blocked?".
