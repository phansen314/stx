# stx v3.0.0 — Why SQLite, not markdown-in-folders

## The question

> Why a SQLite daemon instead of markdown documents in folders viewed with VSCode?
> VSCode already gives the tree structure and a great viewing experience. In general,
> what does stx give us that **obsidian + scripts** (for `next` and the rest) doesn't?

A fair challenge. The short answer: it compares a **document store** to a **graph
engine**. They do different jobs. stx is not a note store with a fancy viewer — it is
a task dependency graph with a lifecycle state machine, and its headline feature is a
*query* over that graph, not a document you read.

---

## Where markdown + obsidian genuinely wins

Concede this honestly. For their job, files are better:

- **Browse tree** — free from VSCode/obsidian, no code to write.
- **Prose and context** — long notes, backlinks, graph view, embeds. Reading and
  linking human knowledge is what obsidian is *for*.
- **Plain text** — git-diffable, greppable, portable, human-editable, no daemon, no
  schema, no server. Survives every tool you'll ever use.

If the workload is mostly **notes with the occasional todo**, obsidian wins. stx does
not try to be that. It deliberately keeps prose/history in an external JSON journal,
not in the DB.

---

## What stx gives that a folder of markdown does not

### 1. `next` — the ready frontier. This is the whole point.

`next` returns the **ready set**: tasks that are not archived, not in a terminal
status, and have **no live `blocks` edge pointing at them from a non-terminal
blocker**. See `docs/stx-v3-next.md` and `src/main/kotlin/stx/service/Frontier.kt`.

That is a **query**, not a document. In SQLite it is a correlated `NOT EXISTS`
anti-join over an indexed edge table, recomputed on every read, so it is never stale.

To get the same answer from markdown you must parse *every* file, reconstruct the
dependency graph in memory, and walk it — on every call. At that point you have
written a query engine and a set of indexes on top of a filesystem. It will be
slower, unindexed, and non-transactional. You didn't avoid the database; you rebuilt a
worse one.

Obsidian's dataview/tasks plugins *can* approximate this — but only by being that
in-memory query layer. The cost doesn't disappear; it moves into a plugin.

### 2. Integrity — files cannot refuse a bad state

The schema (`docs/stx-v3-schema.sql`) and daemon invariants
(`src/main/kotlin/stx/service/Invariants.kt`) enforce structure the filesystem can't:

- Foreign keys (`REFERENCES … ON DELETE RESTRICT`) on every parent link.
- `CHECK` constraints — no self-block, no self-parent, `from <> to` on transitions.
- Partial unique indexes (`WHERE archived=0`) — one live default status, one root
  segment per track, unique live edges, unique live names.
- Application-enforced graph invariants — `blocks` DAG acyclicity, segment-tree
  acyclicity, container archive-cascade in a single transaction.

A markdown file can silently reference a deleted note, introduce a dependency cycle,
or duplicate a name. Nothing stops corruption. stx **rejects** an invalid graph at
write time.

### 3. Concurrency — many writers, no lost updates

You run concurrent Claude sessions and sub-agents against the same store. Multiple
processes editing the same markdown file means lost updates and merge conflicts. stx
serializes through a **single-writer actor**, guards every mutation with an optimistic
`version` compare-and-swap (`UPDATE … WHERE id=? AND version=:expected`), and serves
reads from a consistent WAL snapshot. Agents can hammer it in parallel safely.

### 4. A machine wire, not text-rewriting

Agents speak JSON over HTTP and a stateless CLI; they don't edit prose. Having an LLM
parse and rewrite markdown is lossy and fragments on typos ("in-progress" vs
"In Progress" vs "wip"). stx uses controlled vocabularies — the `status` and
`task_kind` registries — so `next --kind` never splinters. Typed API, not string
surgery.

### 5. Cheap change detection

`/changes` returns one poll token (a monotonic write `seq` plus the schema version).
The TUI and agents poll a single integer instead of re-scanning the whole folder tree
on every refresh.

---

## The tree/viewing point specifically

"VSCode gives the tree and the viewing experience" — true, but the tree is table
stakes, not the value. The stx TUI's worth is the **kanban board filtered to the ready
frontier** and moving a task through its **status state machine** (`[` / `]`). A file
tree cannot show a ready set, cannot move a task along a status DAG, and cannot apply
the `live_task` visibility predicate that hides archived-but-present rows. The tree is
the cheap part; the graph query is the product.

---

## The honest tradeoff

Pick the right tool for the job:

- **obsidian** = a knowledge / prose / context store. Reading, linking, browsing.
- **stx** = a task execution graph. "What's ready," integrity, concurrent machine
  writers.

Notes are documents. Tasks are a dependency graph with a lifecycle. stx bets the
workload is the graph, driven by agents. The price paid: no git-diff of task state, no
free prose editing inside the store. If that bet is wrong for you — mostly notes —
obsidian wins. If it's right — a DAG of tasks with many agents — SQLite already *is*
the transactional, indexed engine you would otherwise reinvent on files.

**One-line rebuttal:** "obsidian + scripts for `next`" means building an unindexed,
non-transactional, single-writer database on top of markdown. stx just uses the
database.

---

See also: `docs/stx-v3-design.md` (model and principles),
`docs/stx-v3-next.md` (frontier spec), `docs/stx-v3-schema.sql` (schema).
