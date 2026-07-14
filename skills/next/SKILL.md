---
name: next
description: Use when the user wants to pick up the next actionable task from an stx workspace — surfaces the ready frontier (unblocked, non-terminal tasks) from the blocks DAG, shows the top task's full context, and optionally offers to move it to an in-progress status. Trigger on "what should I work on", "pick up next task", "what's next", "next task".
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

```sh
stx next -w <ws> --json           # ready tasks only, as a JSON array
# optional scoping:
stx next -w <ws> -t <track> --json
stx next -w <ws> --limit 5 --json
```

`--json` **must follow the subcommand** (`stx next … --json`, not `stx --json next`).
The response is a JSON array of the **ready frontier** — tasks that are unblocked and
non-terminal, ordered by the daemon (priority, then id). Each element:
`{id, title, priority, statusId, segmentId, version}`. There is no separate "blocked"
list in this output.

- **Empty array `[]`** — nothing is ready. Either everything is done or everything left
  is blocked. Run `stx tree -w <ws>` to see which: if all tasks sit in the terminal
  status the workspace is complete (say so and stop); otherwise summarize what's still
  open and what's gating it (blockers show in each task's `stx show`), and stop.
- **Non-empty** — take element `[0]` as the top pick. Note how many others are also ready.

## Step 2 — Hydrate the top task

```sh
stx show <id>                     # text detail (status name, kind, priority, edges)
```

`show` prints the status **name** (the `--json` array only has `statusId`), the priority,
the `kind`, and edge lines — `blocks: #M …` (tasks this one gates, i.e. unlocks when done)
and `blocked by: #K …` (should be empty for a frontier task; flag it if not). Use
`stx tree -w <ws>` if you want the track/segment location and sibling context.

## Step 3 — Present the work order and offer to start

Present a compact summary of the top task: id, title, priority, status, its
track/segment (from `tree`), and what it **unlocks downstream** (its `blocks:` targets).
Mention the count of other ready tasks.

Then offer to start it — do **not** move automatically; wait for confirmation:

```sh
stx mv <id> <in-progress-status>   # positional: <id> then <status name|id>
```

If the in-progress status name is unknown, `stx show <id>` (current status) and
`stx tree -w <ws>` reveal the workspace's statuses; `mv` also prints the legal target
statuses if you attempt an illegal transition. In non-interactive/agentic contexts where
no confirmation is possible, skip the auto-move unless the user pre-authorized transitions.

## Notes

- **No groups, no `--rank`, no `--edge-kind`** — those were the old (pre-v3) CLI. v3
  organizes work as workspace → track → segment → task, ranks the frontier internally,
  and drives readiness off the `blocks` DAG only.
- **Finish + cascade**: `stx done <id>` moves a task to the terminal status; anything
  blocked solely by it becomes ready on the next `stx next`.
