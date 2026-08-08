---
name: next
description: Use when the user wants to pick up the next actionable task from an stx workspace — surfaces the ready frontier (unblocked, non-terminal tasks) from the blocks DAG, claims it when more than one agent is working, shows the top task's full context, and optionally offers to move it to an in-progress status. Trigger on "what should I work on", "pick up next task", "what's next", "next task".
---

Pick up the next actionable task from an stx-v3 workspace.

## The workspace is explicit

stx-v3 is stateless — there is **no active workspace**. You must know which workspace
`-w <name|id>`. If the user didn't say and you don't know, list them first:

```sh
stx ls                 # workspaces (id + name + track count)
```

Pick the relevant one (ask if ambiguous).

## Step 1 — Get the ready frontier

**If you are the only one working**, read it:

```sh
stx next -w <ws> --json           # ready tasks only, as a JSON array
# optional scoping:
stx next -w <ws> -t <track> --json
stx next -w <ws> --limit 5 --json
```

**If other agents or sessions might be working the same workspace**, claim instead of
reading — `next` is a pure read and hands every caller the same top row, so two agents
that both *read* both start the same task:

```sh
stx next -w <ws> --claim --as "<agent-id>" --ttl 15m --limit 1 --json
```

`--claim` computes the frontier **and** reserves what it returns in one transaction, so
two agents racing this are guaranteed different tasks. It returns only what it actually
claimed — an empty array means everything ready is already taken, which is a normal
answer, not an error. Use a stable identifier for `<agent-id>` (a session id); you will
need the same one to release.

`--json` **must follow the subcommand** (`stx next … --json`, not `stx --json next`).
Each element: `{id, title, priority, statusId, segmentId, version, claimedBy,
claimedUntil}`. There is no separate "blocked" list in this output.

- **Empty array `[]`** — nothing is ready *for you*. Either everything is done, everything
  left is blocked, or (with other agents around) everything ready is claimed. Run
  `stx claims -w <ws>` to tell the last case apart from the first two, then
  `stx tree -w <ws>`: if all tasks sit in the terminal status the workspace is complete
  (say so and stop); otherwise summarize what's still open and what's gating it (blockers
  show in each task's `stx show`), and stop.
- **Non-empty** — take element `[0]` as the top pick. Note how many others are also ready.

A task you hold is hidden from *other* agents' `next` but not from your own, as long as
you identify yourself:

```sh
stx next -w <ws> --as "<agent-id>"     # the frontier, including what you already hold
```

## Step 2 — Hydrate the top task

```sh
stx show <id>                     # text detail (status name, kind, priority, edges, lease)
```

`show` prints the status **name** (the `--json` array only has `statusId`), the priority,
the `kind`, a `claimed by: … until: …` line when the task is leased, and edge lines —
`blocks: #M …` (tasks this one gates, i.e. unlocks when done) and `blocked by: #K …`
(should be empty for a frontier task; flag it if not). Use `stx tree -w <ws>` if you want
the track/segment location and sibling context.

## Step 3 — Present the work order and offer to start

Present a compact summary of the top task: id, title, priority, status, its
track/segment (from `tree`), and what it **unlocks downstream** (its `blocks:` targets).
Mention the count of other ready tasks.

Then offer to start it — do **not** move automatically; wait for confirmation:

```sh
stx mv <id> <in-progress-status>   # positional: <id> then <status name|id>
```

**Claiming and moving are different things.** The lease reserves the work so nobody else
picks it up; the status records what stage the work is in. Claim without asking (it is
reversible and self-expiring); move the status only on confirmation. In
non-interactive/agentic contexts where no confirmation is possible, skip the auto-move
unless the user pre-authorized transitions — but still claim, because that is what stops
the double-work.

If the in-progress status name is unknown, `stx show <id>` (current status) and
`stx tree -w <ws>` reveal the workspace's statuses; `mv` also prints the legal target
statuses if you attempt an illegal transition.

## Step 4 — Finish, or let it go

```sh
stx done <id>                      # → terminal status; unblocks whatever it gated
stx release <id> --as "<agent-id>" # give the reservation back
```

Release when you finish *and* when you abandon. A finished task is out of the frontier
either way, but leaving the lease behind makes `stx claims` lie about who is working on
what. If the work outlives the TTL, re-claim to renew:

```sh
stx claim <id> --as "<agent-id>" --ttl 30m    # same call extends your own lease
```

## Notes

- **No groups, no `--rank`, no `--edge-kind`** — those were the old (pre-v3) CLI. v3
  organizes work as workspace → track → segment → task, ranks the frontier internally,
  and drives readiness off the `blocks` DAG only.
- **Finish + cascade**: `stx done <id>` moves a task to the terminal status; anything
  blocked solely by it becomes ready on the next `stx next`.
- **A crash costs nothing.** A lease carries an expiry and nothing sweeps it — the task
  simply returns to the frontier when the TTL lapses. That is also why there is no way to
  steal a lease: if it is still live, someone is presumably still working.
- **`claim` is not a lock on editing.** It reserves *picking*, and deliberately does not
  bump the task's `version`, so it never turns someone else's pending edit into a
  conflict. Concurrent edits are still arbitrated by the optimistic-lock version.
- **Batching**: ids come from stdin with `-`, so `stx next -w <ws> --claim --as me -q |
  stx show -` hydrates everything you just claimed. Exit codes follow grep — 0 results,
  1 empty, 2 error — so `if stx next -w <ws> -q >/dev/null` reads as "is anything ready?".
