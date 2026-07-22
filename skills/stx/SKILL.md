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
- **`-`** in place of an id reads ids from stdin (`show`/`mv`/`edit`/`done`/`block`/`unblock`/
  `relate`/`unrelate`/`archive`); `--desc -` and `meta set <key> -` read the text/JSON from stdin.
  One `-` per command. A batch continues past a failing id and fails at the end.
- **Exit codes follow grep:** 0 results, 1 empty result set (`ls`/`next`/`tree`/`meta ls`/`graph`),
  2 error. So `if stx next -w ws -q >/dev/null; then …` means "is anything ready?".

## Commands

| Command | What |
|---|---|
| `stx ls` | list workspaces (no `-w`) |
| `stx tree -w <ws>` | whole workspace as a tree — the "orient me" view |
| `stx next -w <ws> [-t <track>] [--limit N]` | ready tasks (frontier: unblocked, non-terminal) |
| `stx show <id>` | task detail + edges (blocked-by / blocks / relates) |
| `stx add "<title>" -w <ws> -t <track> [-p N] [--status s] [--kind k] [--desc …]` | create task (`-s <segment-id>` instead of `-t`; `--desc -` reads stdin) |
| `stx mv <id> <status>` | move status (validates transition; prints legal targets if illegal) |
| `stx edit <id> [--title …] [--desc …] [--priority N] [--kind k] [--clear-kind] [--due …]` | edit fields |
| `stx done <id>` | move to the workspace's terminal status |
| `stx block <id> --on <blocker-id>` | make a task blocked by another (feeds `next`) |
| `stx relate <a> --to <b> --kind <k>` | relation edge (e.g. `relates_to`, `spawns`) |
| `stx meta {ls\|get\|set\|del} (--task <id> \| -w <ws> [--track <t>]) [key] [value]` | free-form JSON metadata keys on a task/workspace/track (`set` value is JSON, or `--string` for a literal) |
| `stx graph -w <ws> [-t <track>] [--blocks-only]` | task graph as Graphviz DOT on stdout (pipe to `dot`); `--json` for `{nodes, blocks, relates}` |
| `stx archive task\|segment\|track\|workspace <id> [--yes]` | archive (`--yes` required for track/workspace — cascades) |
| `stx ws new <name>` | new workspace |
| `stx track new <name> -w <ws> [--desc …]` | new track |
| `stx segment new <name> -w <ws> -t <track> [--parent <id>]` | new segment |
| `stx status new <name> -w <ws> --order N [--terminal]` · `status default <s> -w <ws>` · `status archive <s> -w <ws>` | status admin |
| `stx kind new <name> -w <ws>` · `kind archive <name> -w <ws>` | kind admin |
| `stx transition -w <ws> --from <s> --to <s>` | allow a status transition |

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
