# stx

A local, loopback-only task daemon with a terminal UI. Work is organized
**workspace → track → segment → task**; a `blocks` DAG drives a `next`/ready frontier
(the tasks with nothing left blocking them). The daemon speaks JSON over HTTP on
`127.0.0.1`; a Python [Textual](https://textual.textualize.io/) TUI is the front end.

## Prerequisites

- **JDK 21** — for the daemon.
- **Python 3** — for the TUI and the integration script.
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

## Run the TUI

With the daemon running, in another terminal:

```bash
pip install -r tui/requirements.txt
python3 -m tui --base-url http://127.0.0.1:8420
```

The TUI pings the daemon first and exits with a hint if it's unreachable. Key map:
`w`/`b` focus tree/board · `n` new · `e` edit · `a` archive · `[` / `]` move status ·
`f` toggle ready view · `r` refresh · `ctrl+q` quit.

## CLI (`stx`)

A stateless command-line client — handy for scripting and for Claude to drive. Daemon must be
running.

```bash
./bin/stx ls
./bin/stx tree -w <workspace>
./bin/stx next -w <workspace>
./bin/stx add "design schema" -w <workspace> -t <track> -p 2
```

Every workspace-scoped command takes `-w <name|id>` explicitly (nothing is stored, so concurrent
sessions don't clobber each other). Full reference: [`docs/stx-cli.md`](docs/stx-cli.md).

## Demo / integration test

`scripts/dev_sim.py` drives the full API as a "developer" would and asserts state along the
way — a living integration test. It creates its own workspace and **archives it at the end**,
so it leaves the database clean (it's a lifecycle test, not a persistent seeder).

```bash
python3 scripts/dev_sim.py --base-url http://127.0.0.1:8420
```

## Run the tests

```bash
./gradlew test
```

## Project layout

| Path     | What                                              |
|----------|---------------------------------------------------|
| `src/`   | Kotlin daemon (HTTP transport, service, SQLite repo) |
| `stxc/`  | Shared Python wire client (used by the CLI and TUI) |
| `cli/`   | `stx` CLI (`bin/stx`, `python3 -m cli`) — see [`docs/stx-cli.md`](docs/stx-cli.md) |
| `tui/`   | Python Textual TUI (`python3 -m tui`)             |
| `scripts/` | `dev_sim.py` — Python integration test / demo     |
| `docs/`  | Design decisions — see [`docs/stx-v3-decisions.md`](docs/stx-v3-decisions.md) |
