# stx — v3 (Kotlin daemon)

A local, **loopback-only task daemon** with a Go CLI and a Python TUI front end. Work is
organized **workspace → track → segment → task**; a `blocks` DAG drives a `next`/ready
frontier. The daemon is the **sole writer**; clients (Go CLI, Python TUI/CLI, sim) speak
JSON over HTTP on `127.0.0.1:8420`.

Authoritative design lives in `docs/` — start with
[`docs/stx-v3-design.md`](docs/stx-v3-design.md),
[`docs/stx-v3-decisions.md`](docs/stx-v3-decisions.md),
[`docs/stx-v3-schema.sql`](docs/stx-v3-schema.sql), and
[`docs/why-sqlite.md`](docs/why-sqlite.md). This file is the working orientation; the
`docs/` set wins on any conflict.

## Layout

| Path      | What                                                        |
|-----------|-------------------------------------------------------------|
| `src/`    | Kotlin daemon — `Main.kt`, `transport/`, `service/`, `repo/`, `command/`, `dto/`, `error/`, `log/` |
| `src/main/resources/` | `schema.sql`, `log4j2.xml`                       |
| `cmd/stx/`, `internal/` | Go CLI — the **default** `stx` client (`bin/stx-go`) |
| `stxc/`   | Shared Python wire client (used by the Python CLI + TUI + sim) |
| `cli/`    | Python **reference/oracle** CLI (`bin/stx-py`, `python3 -m cli`) — see `docs/stx-cli.md` |
| `tui/`    | Python Textual TUI (`python3 -m tui`)                        |
| `bin/stx` | Bash launcher → Go CLI (`bin/stx-go`), auto-builds on first use, works from any CWD |
| `bin/stx-py` | Bash launcher → Python CLI (sets `PYTHONPATH`)           |
| `scripts/`| `dev_sim.py` — Python integration test / demo               |
| `tests/`  | Python pytest suite (cli / client / tui)                    |
| `packaging/systemd/` | `stx.service` user unit (autostart)              |
| `docs/`   | Authoritative design, schema, decisions                     |

## Build / run / test

```bash
./gradlew run            # start daemon → "stx listening on 127.0.0.1:8420"
./gradlew test           # Kotlin suite (src/test/kotlin/stx)
./gradlew installDist    # build the launched binary → build/install/stx/bin/stx
```

- Port: `STX_PORT` (default **8420**). Clients: `--base-url` / `STX_URL` (default
  `http://127.0.0.1:8420`).
- Data: SQLite in **WAL** mode at `$XDG_STATE_HOME/stx/stx.db` (fallback
  `~/.local/state/stx/stx.db`), created on first run. Singleton `stx.lock` in the same dir.
- Go CLI (default client, needs **Go 1.26+**): `go build -o bin/stx-go ./cmd/stx` (or just run
  `./bin/stx`, which auto-builds on first use); `go test ./internal/...`. Put on PATH:
  `ln -s "$PWD/bin/stx" ~/.local/bin/stx`.
- Python side: `pip install -r tui/requirements.txt`; `python3 -m tui`; the reference CLI via
  `./bin/stx-py`; `pytest` (config in `pyproject.toml`); `python3 scripts/dev_sim.py` (creates +
  archives its own workspace).

Deployed via systemd user unit `packaging/systemd/stx.service` → runs
`build/install/stx/bin/stx`, so a deploy is `./gradlew installDist` + `systemctl --user
restart stx.service` (not a bare `build`).

## Model

```
workspace → track → segment* → task
```

- **workspace** — top-level container and the edge boundary (edges never cross it).
- **track** — root-only anchor (never nests); one coherent line of work; has description +
  metadata. Auto-gets exactly one root segment.
- **segment** — nestable **pure filing** node (no metadata/context/inheritance);
  `parent_segment_id` tree, immutable denormalized `track_id`.
- **task** — the only first-class node: `status_id`, optional `kind`, description, metadata,
  priority, dates.
- **Edges (task↔task only):** `blocks` — directed, acyclic, drives `next`; `relates_to` —
  decorative, cycles OK, `kind` is free text (see decision D6).
- **Lifecycle:** `status` rows are kanban stages (`terminal=1` **is** "done" — no separate
  flag); `status_transition` is the per-workspace legal-move state machine. No `journal`
  table — history is a non-authoritative append-only sidecar log (`journal.log`).

## `next` (the frontier)

A **filter, not a recommender**: a task is in the frontier iff `archived=0`, status not
terminal, and no live `blocks` edge points at it from a non-terminal task. Ordered
`priority DESC, id ASC` (presentation only). **Recompute-on-read, no caching.** Scopes:
`-w` workspace (required), `--track`, `--segment` subtree, `--kind`.

## Invariants

SQLite enforces FKs, CHECKs, and partial-unique indexes. The daemon enforces the graph
invariants SQLite can't, transactionally (`service/Invariants.kt`, `service/StxService.kt`):
`blocks` is a DAG, `segment` parent is acyclic within a track, exactly one root segment per
track, archive cascade (archiving a task archives its incident edges), immutable
`segment.track_id`. Canonical invariant count is **nine** — numbered in `schema.sql` /
`docs/stx-v3-design.md` (decision D1).

## Conventions

- **Stateless CLI — always pass `-w <name|id>`.** No stored "current workspace"; concurrent
  agents/sessions would clobber shared state. Global-id commands (`show`, `mv`, `edit`,
  `done`, `archive`) don't need `-w`. `--json` for machine output.
- **Single write-actor.** All mutations drain one `Channel<Command>` coroutine, each in its
  own transaction, in submission order; reads run concurrently against WAL.
- **Loopback binding is the whole security model** — no auth. Structured JSON error envelope:
  `{error: <variant>, ...variant-specific fields}` (no `kind` key). Status mapping
  Validation→400, NotFound→404, Conflict→409, Gone→410.
- **Optimistic locking**: `mv`/`edit`/`done` do a single CAS on the client-supplied version and
  return `VersionConflict` on mismatch. The one-retry read-modify-write lives in each CLI, not the
  daemon — Go in `internal/cli/cas.go`, Python in `cli/__main__.py` (`_retry_conflict`).
- Sole local user: schema changes edit `src/main/resources/schema.sql` and recreate the DB
  rather than authoring a migration by default.

## Stack

**Daemon:** Kotlin 2.3 / JDK 21, Gradle (Kotlin DSL, committed wrapper), http4k (SunHttp
loopback), kotlinx.serialization, kotlinx.coroutines, plain JDBC + `xerial/sqlite-jdbc`,
`tech.codingzen:railway` for the result type, log4j2. No Spring / gRPC / DI / ORM / auth.

**CLI:** Go 1.26+ with `spf13/cobra` (default client, `cmd/stx` + `internal/`); Python 3
reference/oracle CLI (`cli/`) + Textual TUI (`tui/`) over the shared `stxc` wire client.
