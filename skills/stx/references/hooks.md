# stx Hooks Reference

Hooks are **post-commit observers** — the write always proceeds; hooks observe committed state after the transaction. Each hook is a shell command that receives a JSON payload on stdin describing the event. Exit codes are ignored; failures are silent.

Config lives at `~/.config/stx/hooks.toml`. Commands execute with `shell=True`; anyone who can write that file can run arbitrary code as the stx user — the trust model matches git hooks.

For the CLI subcommands (`stx hook ls|events|validate|schema`), see `cli-reference.md`. The authoritative payload schema is shipped with the package: `stx hook schema`.

---

## Event catalog

All 29 events, grouped by entity. The **category** column determines which extra fields the payload carries (see [Payload structure](#payload-structure)).

### Task events

| Event | Fires on | Category |
|---|---|---|
| `task.created` | `create_task` | created |
| `task.updated` | `update_task` (any field change not covered by a specific event) | updated |
| `task.moved` | `update_task` with `status_id` change | updated |
| `task.done` | `update_task` flipping `done=True`, `mark_task_done`, or auto-flip on entry to a terminal status | updated |
| `task.undone` | `mark_task_undone` | updated |
| `task.archived` | `archive_task` | archived |
| `task.transferred` | `move_task_to_workspace` | transferred |
| `task.assigned` | `update_task` with `group_id` set (non-null) | updated |
| `task.unassigned` | `update_task` with `group_id` cleared to null | updated |
| `task.meta_set` | `set_task_meta`, `replace_task_metadata` (per added/changed key) | meta |
| `task.meta_removed` | `remove_task_meta`, `replace_task_metadata` (per removed key) | meta |

### Group events

| Event | Fires on | Category |
|---|---|---|
| `group.created` | `create_group` | created |
| `group.updated` | `update_group` (any change) | updated |
| `group.archived` | `cascade_archive_group` (top-level only; payload carries `archived_task_ids`, `archived_group_ids` for bulk-archived descendants) | archived |
| `group.meta_set` | `set_group_meta`, `replace_group_metadata` | meta |
| `group.meta_removed` | `remove_group_meta`, `replace_group_metadata` | meta |

### Workspace events

| Event | Fires on | Category |
|---|---|---|
| `workspace.created` | `create_workspace` | created |
| `workspace.updated` | `update_workspace` | updated |
| `workspace.archived` | `cascade_archive_workspace` (top-level only; payload carries `archived_task_ids`, `archived_group_ids`, `archived_status_ids`) | archived |
| `workspace.meta_set` | `set_workspace_meta`, `replace_workspace_metadata` | meta |
| `workspace.meta_removed` | `remove_workspace_meta`, `replace_workspace_metadata` | meta |

### Status events

| Event | Fires on | Category |
|---|---|---|
| `status.created` | `create_status` | created |
| `status.updated` | `update_status` | updated |
| `status.archived` | `archive_status` (bulk paths: `--force` adds `archived_task_ids`; `--reassign-to` adds `reassigned_task_ids` + `reassigned_to`) | archived |

Statuses have no metadata column, so no `status.meta_*` events.

### Edge events

| Event | Fires on | Category |
|---|---|---|
| `edge.created` | `add_edge` | created |
| `edge.archived` | `archive_edge` | archived |
| `edge.updated` | `update_edge` (e.g. acyclic flip) | updated |
| `edge.meta_set` | `set_edge_meta`, `replace_edge_metadata` | meta |
| `edge.meta_removed` | `remove_edge_meta`, `replace_edge_metadata` | meta |

List events from the CLI: `stx hook events`.

---

## Payload structure

Every payload carries these top-level fields:

| Field | Type | Notes |
|---|---|---|
| `event` | string | One of the 29 event names above. |
| `workspace_id` | int \| null | |
| `workspace_name` | string \| null | |
| `entity_type` | `"task"` \| `"group"` \| `"workspace"` \| `"status"` \| `"edge"` | |
| `entity_id` | int \| null | |
| `entity` | object \| null | Full entity snapshot (see `$defs` in `stx hook schema`). |

Then category-specific fields:

**`created`** — adds `proposed: object | null` (the input fields that were passed to the service; mirrors `entity` post-commit) and `changes: null`.

**`updated`** — adds `changes: object` (`{field: {old, new}}` dict) and `proposed: null`.

**`archived`** — adds `changes: object` (always `{archived: {old: bool, new: true}}`) and `proposed: null`.

**`meta`** — adds `meta_key: string`, `meta_value: string | null` (null on `*.meta_removed`), `changes: null`, `proposed: null`.

**`transferred`** — adds `changes: object` (workspace_id old/new), `source_workspace: {id, name}`, `target_workspace: {id, name}`.

Descriptions over 4KB are truncated and marked with `description_truncated: true` on the entity.

Entity shapes are defined in the JSON Schema shipped with the package. Read them programmatically: `stx hook schema | jq '.["$defs"]'`.

---

## Writing hooks

Each hook is a TOML table:

```toml
[[hooks]]
event = "task.created"       # required — exact event name
command = "shell command"    # required — any shell; receives payload on stdin
name = "notify-creator"      # optional — shown by `stx hook ls`; handy for logs
workspace = "work"           # optional — restricts to one workspace; omit for global
enabled = true               # optional — default true; set false to disable without deleting
```

**Matching order:** global hooks fire before workspace-scoped hooks (in config-file order within each group).

**Isolation:** hooks run via `subprocess.Popen` in a new session (`start_new_session=True`). Stdout/stderr redirect to `DEVNULL`. Exit code is ignored; failures are silent.

---

## Recipe library

Polished, working examples. Copy-paste into `~/.config/stx/hooks.toml` and run `stx hook validate` first.

### 1. Desktop notify on task completion

```toml
[[hooks]]
event = "task.done"
name = "notify-done"
command = '''jq -r '"✓ " + .entity.title + " done"' | xargs -I{} notify-send "stx" "{}"'''
```

### 2. Enforce creation rules before running stx

Hooks are post-commit observers — they cannot veto a write. For validations
like "require a non-empty description" or "disallow certain task titles",
implement the check as a wrapper script or alias that runs `stx task create`
only after passing your pre-flight conditions.

### 3. Detect unwanted archives after the fact

Post-commit `workspace.archived` or `group.archived` hooks can alert when an
archive has occurred. If you need to prevent certain archives, implement the
guard as a wrapper that calls `stx ... archive` only after confirming
preconditions are met.

### 4. Slack webhook on high-priority task moved to review

```toml
[[hooks]]
event = "task.moved"
name = "slack-review"
command = '''
read payload
priority=$(echo "$payload" | jq -r '.entity.priority')
title=$(echo "$payload" | jq -r '.entity.title')
if [ "$priority" -ge 3 ]; then
  curl -sS -X POST -H 'Content-Type: application/json' \
    -d "{\"text\":\"⚠ high-pri task moved: $title\"}" \
    "$SLACK_WEBHOOK_URL"
fi
'''
```

### 5. JSONL activity log (one hook per event, or pick the ones you care about)

```toml
[[hooks]]
event = "task.updated"
name = "audit-log"
command = "jq -c '{ts: now|strftime(\"%FT%T\"), event, entity: .entity.title, changes}' >> ~/.local/share/stx/activity.jsonl"

[[hooks]]
event = "task.archived"
name = "audit-log"
command = "jq -c '{ts: now|strftime(\"%FT%T\"), event, entity: .entity.title}' >> ~/.local/share/stx/activity.jsonl"
```

### 6. Git-sync an Obsidian vault file on group rename

```toml
[[hooks]]
event = "group.updated"
name = "vault-sync"
command = '''
read payload
old=$(echo "$payload" | jq -r '.changes.title.old // empty')
new=$(echo "$payload" | jq -r '.changes.title.new // empty')
[ -n "$old" ] && [ -n "$new" ] || exit 0
cd ~/vault && git mv "groups/$old.md" "groups/$new.md" 2>/dev/null && \
  git commit -m "rename group $old → $new" -- "groups/$new.md"
'''
```

### 7. Detect and log deprecated edge kinds

Hooks cannot veto edge creation. To block a deprecated `kind`, use a wrapper
script that checks the `--kind` argument before calling `stx edge create`.
To *observe* which deprecated kinds are being created after the fact:

```toml
[[hooks]]
event = "edge.created"
name = "log-legacy-edges"
command = '''
read payload
kind=$(echo "$payload" | jq -r '.entity.kind')
if [ "$kind" = "legacy-relates" ]; then
  echo "$(date -Iseconds) legacy-relates edge created" >> ~/.local/share/stx/edge-audit.log
fi
'''
```

### 8. Cross-workspace transfer notification

```toml
[[hooks]]
event = "task.transferred"
name = "transfer-notify"
command = '''
read payload
title=$(echo "$payload" | jq -r '.entity.title')
src=$(echo "$payload" | jq -r '.source_workspace.name')
tgt=$(echo "$payload" | jq -r '.target_workspace.name')
notify-send "stx" "$title: $src → $tgt"
'''
```

### 9. Conditional tag on `task.meta_set`

```toml
[[hooks]]
event = "task.meta_set"
name = "pr-link-notify"
command = '''
read payload
key=$(echo "$payload" | jq -r '.meta_key')
val=$(echo "$payload" | jq -r '.meta_value')
if [ "$key" = "pr_url" ]; then
  notify-send "stx" "PR linked: $val"
fi
'''
```

### 10. Clean up external resources for bulk-archived tasks

`group.archived` and `workspace.archived` carry `archived_task_ids` in the payload. Use them to fan out any per-task cleanup without wiring `task.archived`:

```toml
[[hooks]]
event = "group.archived"
name = "cleanup-bulk-archived"
command = '''
read payload
echo "$payload" | jq -r '.archived_task_ids // [] | .[]' | while read -r task_id; do
  echo "Cleaning up task $task_id"
  # e.g. close Linear issue, delete git worktree, etc.
done
'''
```

`status.archived --reassign-to X` carries `reassigned_task_ids` and `reassigned_to`:

```toml
[[hooks]]
event = "status.archived"
name = "notify-reassigned"
command = '''
read payload
target=$(echo "$payload" | jq -r '.reassigned_to // empty')
if [ -n "$target" ]; then
  echo "$payload" | jq -r '.reassigned_task_ids[] | "task \(.) moved to status '"$target"'"'
fi
'''
```

### 11. Disabled hook (kept around for later)

```toml
[[hooks]]
event = "task.done"
name = "confetti"
command = "echo 🎉"
enabled = false
```

---

## Gotchas

- **`timing` field is gone.** stx hooks are post-only observers — the `timing` field is no longer used and should be removed from your hooks.toml. `timing = "pre"` is still a config error with a migration hint; any other `timing` value is silently ignored.
- **Hook isolation:** hooks never raise back to the caller — don't rely on them for control flow.
- **Description truncation at 4KB** (`DESCRIPTION_MAX_BYTES`). Truncated payloads include `"description_truncated": true` on the entity so hooks can detect it.
- **Recursive invocation:** a hook that runs `stx ...` inside itself will recursively fire more hooks with no depth limit. Avoid self-referential hooks.
- **Bulk archives** (`cascade_archive_group`, `cascade_archive_workspace`, `archive_status --force/--reassign-to`) emit only the top-level `*_ARCHIVED` event. Per-entity hooks for bulk-affected descendants are intentionally skipped. The affected IDs are included in the payload: `archived_task_ids`, `archived_group_ids`, `archived_status_ids` (cascade ops), `reassigned_task_ids` + `reassigned_to` (`archive_status --reassign-to`). These fields are absent when there are no affected entities.
- **Statuses have no metadata**, so `status.meta_*` events don't exist.

---

## Testing

Before deploying a hook, validate the config:

```bash
stx hook validate
stx hook validate --path /tmp/staged-hooks.toml    # dry-run an alternate file
```

Inspect what's wired up:

```bash
stx hook ls                              # all hooks
stx hook ls --event task.created         # by event
stx hook ls --workspace work             # by workspace
stx hook ls --globals-only               # hooks without a workspace scope
```

Hand-play a hook command without mutating the DB — pipe a synthetic payload into the command:

```bash
echo '{"event":"task.done","entity":{"title":"test"}}' | \
  jq -r '"✓ " + .entity.title + " done"'
```

For round-trip testing against the running DB, the included smoke script exercises every `stx hook` subcommand end-to-end:

```bash
bash scripts/smoke-hooks.sh
```
