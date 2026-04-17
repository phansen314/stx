---
name: next
description: Use when the user wants to pick up the next actionable task from an stx workspace — surfaces the highest-priority ready task from the dependency DAG (default edge kind `blocks`, configurable per workspace), shows its full context (description, group, edges, history), and optionally offers to move it to an in-progress status. Trigger on: "what should I work on", "pick up next task", "what's next", "next task".
---

Pick up the next actionable task from the active stx workspace.

## Step 1 — Get the ready frontier

Default edge kind is `blocks`. If the workspace uses a different kind (e.g.
`spawns`, `depends-on`, project-specific kind), pass one or more `--edge-kind`
flags. If the user explicitly named a kind in their request, forward it. If the
user typically uses a non-default kind, ask once and remember.

```sh
# Default — blocks DAG
stx --json next --rank

# Custom single kind
stx --json next --rank --edge-kind spawns

# Multiple kinds unioned into one DAG
stx --json next --rank --edge-kind blocks --edge-kind spawns
```

Parse the response:

- **Both `ready` and `blocked` are empty** — the workspace is complete. All tasks are
  done. Report this and stop.
- **`ready` is empty but `blocked` is non-empty** — nothing is currently actionable.
  Show a summary of the `blocked` list (what's gated and what's blocking it), then
  stop. Suggest completing the pending blocker tasks first.
- **`ready[0].done = true`** — stale rollup edge case; skip it and use `ready[1]`.
  If all ready tasks have `done=true`, treat as the "workspace complete" case above.
- **`ready` has items** — proceed with `ready[0]` (highest-priority by rank). Note
  how many other tasks are also on the frontier.

## Step 2 — Hydrate the top task (data only, no output yet)

```sh
stx --json task show <task-id>
```

Collect:
- Task number, title, priority, due date, done flag, version
- Description (if set)
- Status name and `is_terminal` flag
- Group title (if assigned)
- `edge_targets`: outgoing edges — tasks/groups this task must complete before they
  can start
- `edge_sources`: incoming edges — tasks/groups that must complete before this one
  (should be empty on the frontier; note any non-empty ones as unexpected blockers)
- Last 3 history entries (ask user for more if relevant)

Do not collect or render the task's `metadata` blob — it can be arbitrarily large
(keys + 500-char values each). If the user asks for it, run
`stx --json task meta ls <task-id>` on demand.

## Step 3 — Group context (data only, no output yet; skip if no group)

```sh
stx --json group show "<group-title>"
```

Collect:
- Group ancestry path (workspace → parent → … → group)
- Sibling tasks in the same group and their done state
- `group.done` — whether the group as a whole is complete

## Step 4 — Downstream gates (data only, no output yet)

From the same `stx next` output parsed in Step 1 (with whatever `--edge-kind` was
used), find all entries in `blocked` whose `blocked_by` array contains this task's
ID. These are the tasks directly gated on completing this one.
`blocked_by` contains task IDs only — format them as `task-NNNN`. Titles are not
available without additional lookups; show IDs unless you have the title from the
`ready` or `blocked` lists already.

## Step 5 — Present work order and offer to start

Present everything collected in Steps 1–4 as a single output:

```
━━━ Next Task ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  task-NNNN  [priority P]  <title>
  Status:    <status>
  Group:     workspace → group → subgroup   (omit if no group)
  Due:       <date or —>

  <description>                              (omit if empty; see truncation note)

  Unlocks downstream:
    task-MMMM  (title if available, else just the id)
    task-PPPP  …

  Unexpected incoming blockers:             (omit if empty)
    task-XXXX  …

  Recent history:
    <field>: <old> → <new>  (source, timestamp)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

**Description truncation** — render the first 10 lines as Markdown. If longer,
append `… (N more lines)` and offer to display the rest on request. User can ask
for a different limit.

**Offer to start** — if `is_terminal=false` and `done=false`, offer to move the task
to an in-progress status:

```sh
stx task mv <task-id> -S "<in-progress-status>"
```

If the correct status name is unknown, list options first:

```sh
stx --json status ls
```

**Do not move automatically** — wait for user confirmation. In non-interactive /
agentic contexts where no confirmation is possible, skip the offer unless the user
has pre-authorised status transitions.

## Edge cases

- **No active workspace** — run `stx workspace ls` to list options, then
  `stx workspace use <name>`.
- **No tasks exist** — workspace is empty; suggest creating tasks or seeding from a
  plan.
- **No dependency edges** — all tasks are on the frontier; `stx next --rank` still
  sorts by priority, due date, id — the result is correct, just unordered by
  dependency.
- **User wants more candidates** — rerun with `stx --json next --rank --limit N` and
  let them choose from the top N.
- **Mixed edge-kind conventions in one workspace** — run once per kind, or union
  them via repeated `--edge-kind` flags (see Step 1).
