---
name: next
description: Use when the user wants to pick up the next actionable task from an stx workspace — surfaces the highest-priority ready task from the blocks DAG, shows its full context (description, group, edges, metadata, history), and optionally marks it in-progress. Trigger on: "what should I work on", "pick up next task", "what's next", "next task".
---

Pick up the next actionable task from the active stx workspace.

## Step 1 — Get the ready frontier

```sh
stx next --rank --json
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
stx task show <task-id> --json
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
- Metadata key/value pairs (branch, jira, owner, etc.)
- Last 3 history entries

## Step 3 — Group context (data only, no output yet; skip if no group)

```sh
stx group show "<group-title>" --json
```

Collect:
- Group ancestry path (workspace → parent → … → group)
- Sibling tasks in the same group and their done state
- `group.done` — whether the group as a whole is complete

## Step 4 — Downstream gates (data only, no output yet)

From the `stx next` output, find all entries in `blocked` whose `blocked_by` array
contains this task's ID. These are the tasks directly gated on completing this one.
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

  <description rendered as Markdown, if set>

  Metadata:  branch=feat/x  jira=PROJ-42    (omit if empty)

  Unlocks downstream:
    task-MMMM  <title if known, else task-MMMM>
    task-PPPP  …

  Unexpected incoming blockers:             (omit if empty)
    task-XXXX  …

  Recent history:
    <field>: <old> → <new>  (source, timestamp)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

**Offer to start** — if `is_terminal=false` and `done=false`, offer to move the task
to an in-progress status:

```sh
stx task mv <task-id> -S "<in-progress-status>"
```

If the correct status name is unknown, list options first:

```sh
stx status ls --json
```

**Do not move automatically** — wait for user confirmation. In non-interactive /
agentic contexts where no confirmation is possible, skip the offer unless the user
has pre-authorised status transitions.

## Edge cases

- **No active workspace** — run `stx workspace ls` to list options, then
  `stx workspace use <name>`.
- **No tasks exist** — workspace is empty; suggest creating tasks or seeding from a
  plan.
- **No blocking edges** — all tasks are on the frontier; `stx next --rank` still
  sorts by priority, due date, id — the result is correct, just unordered by
  dependency.
- **Different DAG edge kind** — pass `--edge-kind <kind>` to `stx next` if the
  workspace uses a kind other than `blocks`.
- **User wants more candidates** — rerun with `stx next --rank --limit N --json` and
  let them choose from the top N.
