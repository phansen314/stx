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
- **Graph:** `graph -w <ws> [-t <track>] [--blocks-only] [--vertical] [-o <name> [--svg|--png|--pdf]]`
  — emit the task graph as Graphviz DOT on stdout (`blocks` solid, `relates_to` dashed; done nodes
  filled), left-to-right unless `--vertical` (top-to-bottom). Pipe to `dot`
  (`stx graph -w auth | dot -Tsvg -o auth.svg`), or render directly with `-o` (needs Graphviz
  `dot` on PATH). Give `-o` a **bare name** and a format flag — `stx graph -w auth -o auth --png`
  writes `auth.png`; with no flag it defaults to SVG (`-o auth` → `auth.svg`). A format flag
  **overrides any extension you type** (`-o auth.svg --png` → `auth.png`); a typed extension with no
  flag works if it's `.svg/.png/.pdf`, else it errors (no silently mislabeled files). `--json` emits
  `{nodes, blocks, relates}` instead (mutually exclusive with `-o`). Seed a throwaway db and render
  samples with `scripts/graph_demo.sh`.
  - **Styling** (`--style <file>`, `--no-style`): colors/attributes come from a TOML config at
    `$XDG_CONFIG_HOME/stx/graph.toml` (fallback `~/.config/stx/graph.toml`), optionally overlaid by
    `--style <file>` (deep-merged); `--no-style` uses built-in defaults only. Style task nodes by
    status name, kind, priority, or the terminal fallback, and edges by type/kind — every value is a
    raw Graphviz attribute. Example:
    ```toml
    [status.Done]                # color a task green when it's done
    style = "rounded,filled"
    fillcolor = "#cde7cd"
    [kind.bug]
    color = "#b00020"
    [[priority]]
    min = 5
      [priority.style]
      penwidth = "2.5"
    [relates_kind.spawns]
    color = "#3355ff"
    ```
  - **Clustering** (`--cluster none|track|segment`, default `none`): group task nodes into Graphviz
    clusters by track or by the nested segment tree; style clusters via `[track]`/`[track_name.<n>]`
    and `[segment]`/`[segment_name.<n>]`, and the whole graph via `[workspace]`.
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

Completion covers every command's live arguments, for example:

- **task ids** — `show`/`edit`/`done`/`mv` first arg, and `block`/`unblock --on`, `relate`/`unrelate --to`, `meta --task`
- **`mv <id> <TAB>`** — only the *legal* target statuses for that task
- **workspaces** — every `-w/--workspace`; **`--track`** — that workspace's tracks
- **enums** — `add --status`/`--kind`, `transition --from`/`--to`, `status default|archive <status>`, `kind archive <name>`, `relate --kind` (kinds already in use)
- **`archive <TAB>`** — the entity type, then live ids of that type across workspaces
- **`meta get|set|del <TAB>`** — the metadata keys already set on the target entity

Completion dials fresh each time and offers nothing (never errors) when the daemon is down.
