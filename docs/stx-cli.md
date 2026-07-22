# stx CLI

A thin, **stateless** command layer over the stx daemon — for agents and humans. Two
interchangeable implementations sit behind one wire contract (the same the TUI and
`scripts/dev_sim.py` speak): a **Go** client (the default) and a **Python** reference/oracle.
Same commands, same flags — pick whichever is convenient.

## Install / run

The daemon must be running (`./gradlew run`, listens on `127.0.0.1:8420`).

### Go CLI — the default

`bin/stx` runs the compiled Go client (`bin/stx-go`) and **builds it on first use**
(`go build -o bin/stx-go ./cmd/stx`), so you need **Go 1.26+** installed. Source: `cmd/stx` +
`internal/cli`.

```bash
./bin/stx ls                       # from the repo root (any CWD works)
ln -s "$PWD/bin/stx" ~/.local/bin/stx   # optional: put it on PATH
```

### Python CLI — the reference/oracle

`bin/stx-py` runs the original Python implementation (`python3 -m cli`), kept for
cross-checking. No Go required; the launcher sets `PYTHONPATH` so the repo's `stxc` client
is importable regardless of CWD.

```bash
./bin/stx-py ls                    # from the repo root
PYTHONPATH=/path/to/stx python3 -m cli ls   # or invoke the module directly
```

Daemon location (both CLIs): `--base-url` flag or `STX_URL` env (default
`http://127.0.0.1:8420`).

## Stateless by design — always pass `-w`

There is **no stored "current workspace."** Every workspace-scoped command takes `-w <name|id>`
explicitly. This is intentional: multiple agents / concurrent sessions would clobber any shared or
env-based "current context" (and Claude Code's shell state doesn't even persist between calls).
Nothing is written to disk; each command fully self-describes. Workspace-keyed commands without a
resolvable `-w` exit non-zero with a hint. Commands keyed by a global id (`show`, `mv`, `edit`,
`done`, `archive`) don't need `-w`.

Add `--json` to any command for raw output (pipe to `jq`); the default is compact text.

## Command reference

See the table and recipes in [`skills/stx/SKILL.md`](../skills/stx/SKILL.md) — it's
the single source for the command list. In short:

- **Orient:** `ls`, `tree -w <ws>`, `next -w <ws> [-t <track>]`, `show <id>`
- **Tasks:** `add`, `mv <id> <status>`, `edit`, `done`, `block`, `relate`, `archive`
- **Metadata:** `meta {ls|get|set|del} (--task <id> | -w <ws> [--track <t>]) [key] [value]` —
  free-form JSON key/values on a task, workspace, or track (`set` parses the value as JSON,
  falling back to a string; `--string` forces a literal string)
- **Graph:** `graph -w <ws> [-t <track>] [--blocks-only]` — emit the task graph as Graphviz DOT
  on stdout (`blocks` solid, `relates_to` dashed; done nodes filled). Pipe to `dot`:
  `stx graph -w auth | dot -Tsvg -o auth.svg`. `--json` emits `{nodes, blocks, relates}` instead.
- **Containers/registries:** `ws new`, `track new`, `segment new`, `status …`, `kind …`, `transition`

Optimistic-lock versions are handled automatically by `mv`/`edit`/`done` (read-modify-write with one
retry on conflict). Illegal status moves print the legal targets.

## Interactive helpers (Go CLI)

Two conveniences that surface live daemon data so you never hand-copy an id — both are Go-only and
degrade gracefully when their dependency (fzf / the daemon) is absent.

### Bare `stx` — guided fzf builder

Run **`stx`** with no arguments in a terminal and it walks you through assembling a command: an fzf
menu of every builder-covered command (the task loop `add`/`mv`/`done`/`edit`/`show`/`next`/`tree`,
edges `block`/`unblock`/`relate`/`unrelate`/`relate-kinds`, plus `graph`, `meta`, `archive`, and the
`ws`/`track`/`segment`/`status`/`kind`/`transition` admin), then live pickers for each argument —
workspace, task (`#id [status] title`, with `stx show` in the preview pane), segments, statuses,
kinds — and for `mv` **only the legal next statuses** for the chosen task. Commands with
subcommands (`meta`, `status`, `kind`, `archive` types) pick the sub/target first. Each pane frames
the command as built so far on its border. The assembled `stx …` is printed for a `run? [Y/n]`
confirm, then executed. fzf drives everything from inside the binary (via `os/exec`) — no shell
wrapper.

Non-interactive (piped or scripted) `stx` prints help instead; without fzf on PATH the builder
prints an install hint and exits cleanly.

### Dynamic shell completion

Cobra's stock completion, wired to live data:

```bash
eval "$(stx completion bash)"      # or: zsh | fish  (add to ~/.bashrc)
```

`stx show <TAB>` / `stx mv <TAB>` offer real task ids; `stx mv <id> <TAB>` offers the legal target
statuses; `stx add -w <TAB>` offers workspaces, `--track`/`--status`/`--kind <TAB>` offer that
workspace's values. Completion dials fresh each time and offers nothing (never errors) when the
daemon is down.
