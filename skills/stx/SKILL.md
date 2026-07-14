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

## Commands

| Command | What |
|---|---|
| `stx ls` | list workspaces (no `-w`) |
| `stx tree -w <ws>` | whole workspace as a tree — the "orient me" view |
| `stx next -w <ws> [-t <track>] [--limit N]` | ready tasks (frontier: unblocked, non-terminal) |
| `stx show <id>` | task detail + edges (blocked-by / blocks / relates) |
| `stx add "<title>" -w <ws> -t <track> [-p N] [--status s] [--kind k] [--desc …]` | create task (`-s <segment-id>` instead of `-t`) |
| `stx mv <id> <status>` | move status (validates transition; prints legal targets if illegal) |
| `stx edit <id> [--title …] [--desc …] [--priority N] [--kind k] [--clear-kind] [--due …]` | edit fields |
| `stx done <id>` | move to the workspace's terminal status |
| `stx block <id> --on <blocker-id>` | make a task blocked by another (feeds `next`) |
| `stx relate <a> --to <b> --kind <k>` | relation edge (e.g. `relates_to`, `spawns`) |
| `stx archive task\|segment\|track\|workspace <id> [--yes]` | archive (`--yes` required for track/workspace — cascades) |
| `stx ws new <name>` | new workspace |
| `stx track new <name> -w <ws> [--desc …]` | new track |
| `stx segment new <name> -w <ws> -t <track> [--parent <id>]` | new segment |
| `stx status new <name> -w <ws> --order N [--terminal]` · `status default <s> -w <ws>` · `status archive <s> -w <ws>` | status admin |
| `stx kind new <name> -w <ws>` · `kind archive <name> -w <ws>` | kind admin |
| `stx transition -w <ws> --from <s> --to <s>` | allow a status transition |

`mv`/`edit`/`done` handle the optimistic-lock `version` automatically (read-modify-write, one retry
on conflict). Errors print as `error: <Variant>: …` with a non-zero exit.

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

**Plan a small chunk:**
```
stx add "design schema" -w auth-rewrite -t build -p 2
stx add "write migration" -w auth-rewrite -t build
stx block <migration-id> --on <schema-id>   # migration waits for schema
```
