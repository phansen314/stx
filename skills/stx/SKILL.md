---
name: stx
description: Drive the stx task daemon from the shell — create/list/move tasks across workspaces, tracks, segments. Use when tracking work in stx-v3 (workspace → track → segment → task with a blocks-DAG "next" frontier).
---

# stx CLI

Stateless CLI over the stx daemon — run `stx …` (it's on PATH). The daemon **autostarts**
on login via a systemd user service and listens on `127.0.0.1:8420` (override with
`--base-url` or `STX_URL`). If a command errors with a connection failure, start it:
`systemctl --user start stx.service`.

## The one rule: always pass `-w`

There is **no stored "current workspace"** — every workspace-scoped command takes `-w <name|id>`
explicitly. This is deliberate: multiple Claude sessions and sub-agents run concurrently, and any
shared/implied context would clobber across them. Names or numeric ids work everywhere. Add `--json`
to any command for machine-readable output; text is the compact default.

## Composition — `-q`, `-`, exit codes

- **`-q/--quiet`** prints ids only, one per line (`meta get -q` prints the bare value, `meta ls -q`
  the keys). Mutually exclusive with `--json`. This is how you capture an id: `id=$(stx add … -q)`.
- **`-`** in place of an id reads ids from stdin (`show`/`blockers`/`mv`/`edit`/`done`/`block`/`unblock`/
  `relate`/`unrelate`/`archive`); `--desc -` and `meta set <key> -` read the text/JSON from stdin.
  One `-` per command. A batch continues past a failing id and fails at the end.
- **Exit codes follow grep:** 0 results, 1 empty result set
  (`ls`/`next`/`blockers`/`tree`/`meta ls`/`graph`/`status ls`/`relate-kinds`), 2 error. So
  `if stx next -w ws -q >/dev/null; then …` means "is anything ready?", and
  `if stx blockers 42 -q >/dev/null; then …` means "is #42 blocked?".

## Commands

| Command | What |
|---|---|
| `stx ls` | list workspaces (no `-w`) |
| `stx tree -w <ws>` | whole workspace as a tree — the "orient me" view |
| `stx next -w <ws> [-t <track>] [-s <segment-id>] [--kind k] [--limit N]` | ready tasks (frontier: unblocked, non-terminal); `-s` scopes to a segment subtree, `--kind` to a work type |
| `stx show <id>` | task detail + edges (blocked-by / blocks / relates) |
| `stx blockers <id> [--depth N]` | **inverse of `next`** — the unfinished work blocking this task, transitively, shallowest hop first. `-q` prints the *blocker* ids (so `stx blockers 42 -q \| stx done -` clears the path); exit 1 = nothing is blocking it |
| `stx add "<title>" -w <ws> -t <track> [-s <segment>] [-p N] [--status s] [--kind k] [--desc …] [-e]` | create task. `-s` takes a segment **name or id** and resolves within `-t`, exactly like `refile -s`; `-s <id>` alone works without `-t`. `--desc -` reads stdin, `-e` writes the description in `$EDITOR` |
| `stx mv <id> <status>` | move status (validates transition; prints legal targets if illegal) |
| `stx refile <id> -w <ws> -t <track> [-s <segment>]` | re-file a task under another track/segment (`mv` on the filing axis; `-s` names a segment in that track, default its root). Same workspace only; `-` reads ids from stdin |
| `stx edit <id> [--title …] [--desc …] [--priority N] [--kind k \| --no-kind] [-e]` | edit fields; **no field flag on a terminal (or `-e`) opens the description in `$EDITOR`** — whole buffer = description, `unchanged #id` when you close it untouched |
| `stx done <id>` | move to the workspace's terminal status |
| `stx block <id> --on <blocker-id>` · `stx unblock <id> --on <blocker-id>` | add / remove a blocks edge (feeds `next`) |
| `stx relate <a> --to <b> --kind <k>` · `stx unrelate <a> --to <b> --kind <k>` | add / remove a relation edge (e.g. `relates_to`, `spawns`) |
| `stx relate-kinds -w <ws>` | list the relation kinds currently in use |
| `stx meta {ls\|get\|set\|del} (--task <id> \| -w <ws> [--track <t>]) [key] [value]` | free-form JSON metadata keys on a task/workspace/track (`set` value is JSON, or `--string` for a literal; `set … -e` edits the value in `$EDITOR` — JSON by default, raw text with `--string`) |
| `stx graph -w <ws> [-t <track>] [--blocks-only]` | task graph as Graphviz DOT on stdout (pipe to `dot`); `--json` for `{nodes, blocks, relates}` |
| `stx archive task\|segment\|track\|workspace <id> [--yes]` | archive (`--yes` required for track/workspace — cascades) |
| `stx ws new <name>` · `stx ws rename <new-name> -w <ws>` | create / rename a workspace |
| `stx track new <name> -w <ws> [--desc …]` · `stx track edit <track> -w <ws> [--name …] [--desc …]` | create / edit a track |
| `stx segment new <name> -w <ws> -t <track> [--parent <id>]` · `segment edit <segment> -w <ws> -t <track> [--name …] [--under <parent>]` | create / rename / reparent a segment (reparent stays inside the track; the root can be renamed, not moved) |
| `stx status ls -w <ws>` · `status new <name> -w <ws> --order N [--terminal]` · `status default <s> -w <ws>` · `status archive <s> -w <ws>` · `status edit <s> -w <ws> [--name …] [--order N]` · `status order <s1> <s2> … -w <ws>` | status admin — `edit` renames/renumbers one, `order` sets the kanban order in one txn (listed first, the rest behind them). `terminal` is not editable |
| `stx kind new <name> -w <ws>` · `kind archive <name> -w <ws>` · `kind rename <old> <new> -w <ws>` | kind admin (a rename keeps the id, so typed tasks stay typed) |
| `stx transition -w <ws> --from <s> --to <s>` | allow a status transition |
| `stx claim <id> --as <agent> [--ttl 15m]` · `stx release <id> --as <agent>` | reserve a task for an agent / drop the lease. `claim` on a task you already hold **renews** it (no separate heartbeat verb). A leased task leaves everyone else's `next` |
| `stx next -w <ws> --claim --as <agent> [--ttl 15m] [--limit N]` | **the agent loop** — frontier + reservation in one transaction, so two agents never get the same task. `-q` pipes the claimed ids |
| `stx next -w <ws> --as <agent>` | frontier including the leases *you* hold (without `--as`, every leased task is hidden) |
| `stx claims -w <ws>` | who holds what, and until when (live leases only) |
| `stx version` (or `--version`) | client version, plus the daemon's schema/seq when it's up — works with the daemon down |

`mv`/`edit`/`done` handle the optimistic-lock `version` automatically (read-modify-write, one retry
on conflict). Errors print as `error: <Variant>: …` on stderr and exit 2.

## Recipes

**Orient** — what exists, what's ready:
```
stx ls
stx tree -w auth-rewrite
stx next -w auth-rewrite
```

**Pick next + start it:**
```
stx next -w auth-rewrite          # grab the top id
stx mv 42 in-progress
```

**Finish + unblock downstream:**
```
stx done 42                       # 42 → terminal; anything blocked only by 42 now appears in `next`
stx next -w auth-rewrite
```

**Why isn't this ready?** (the inverse read — note blockers may live in another track):
```
stx blockers 42                        # everything unfinished in #42's way, shallowest hop first
stx blockers 42 -q | stx done -        # clear the whole path
```

**Clear a whole ready set (pipe ids, no copying):**
```
stx next -w auth-rewrite -t build -q | stx done -
```

**Plan a small chunk:**
```
stx add "design schema" -w auth-rewrite -t build -p 2
stx add "write migration" -w auth-rewrite -t build
stx block <migration-id> --on <schema-id>   # migration waits for schema
```
