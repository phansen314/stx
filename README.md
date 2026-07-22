# stx

A local, loopback-only task daemon with a command-line front end. Work is organized
**workspace → track → segment → task**; a `blocks` DAG drives a `next`/ready frontier
(the tasks with nothing left blocking them). The daemon speaks JSON over HTTP on
`127.0.0.1`; the Go `stx` CLI is the client.

## Prerequisites

- **JDK 21** — for the daemon.
- **Go 1.26+** — for the `stx` CLI (the client). Only needed to build it; the
  `bin/stx` launcher compiles it on first use.
- Gradle is **not** required separately; use the committed wrapper (`./gradlew`).

## Run the daemon

```bash
./gradlew run
```

On start it prints:

```
stx listening on 127.0.0.1:8420
```

- Port defaults to **8420**; override with `STX_PORT=9000 ./gradlew run`.
- Data lives in a SQLite database (WAL mode), created on first run at
  `$XDG_STATE_HOME/stx/stx.db`, falling back to `~/.local/state/stx/stx.db`.
- To start the daemon automatically on login, see [docs/autostart.md](docs/autostart.md).

## CLI (`stx`)

A stateless command-line client — handy for scripting and for Claude to drive. Daemon must be
running.

```bash
./bin/stx ls
./bin/stx tree -w <workspace>       # workspace hierarchy as a linux-`tree`-style view
./bin/stx next -w <workspace>
./bin/stx add "design schema" -w <workspace> -t <track> -p 2
./bin/stx graph -w <workspace> -o graph.svg   # render the blocks DAG via Graphviz
```

Every workspace-scoped command takes `-w <name|id>` explicitly (nothing is stored, so concurrent
sessions don't clobber each other). Full reference: [`docs/stx-cli.md`](docs/stx-cli.md).

`bin/stx` runs the compiled Go client (`bin/stx-go`), **building it on first use** with
`go build -o bin/stx-go ./cmd/stx` (needs Go 1.26+). Source lives in `cmd/stx` + `internal/cli`.
Put it on your PATH:

```bash
ln -s "$PWD/bin/stx" ~/.local/bin/stx
```

Don't want to memorize ids? Run bare **`stx`** in a terminal — an fzf-driven builder assembles a
command from live daemon data. `eval "$(stx completion bash)"` adds `<TAB>` completion for
ids/workspaces/statuses. See
[`docs/stx-cli.md`](docs/stx-cli.md#interactive-helpers).

## Run the tests

```bash
./gradlew test              # Kotlin daemon suite
go test ./internal/...      # Go CLI suite
```

## Project layout

| Path     | What                                              |
|----------|---------------------------------------------------|
| `src/`   | Kotlin daemon (HTTP transport, service, SQLite repo) |
| `cmd/stx/`, `internal/` | Go CLI — the `stx` client (`bin/stx-go`)   |
| `bin/`   | Launchers — `stx` (→ Go, auto-builds), `stx-go` (compiled binary) |
| `scripts/` | `graph_demo.sh` / `graph_bigdemo.sh` — seed an isolated daemon + render styled graphs; `smoke-go.sh` — Go CLI smoke test |
| `docs/`  | Design decisions — see [`docs/stx-v3-decisions.md`](docs/stx-v3-decisions.md) |
