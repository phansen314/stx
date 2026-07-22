# stx CLI

A thin, **stateless** command layer over the stx daemon — for agents and humans. A single
**Go** client speaks the wire contract; same commands, same flags from any CWD.

## Install / run

The daemon must be running (`./gradlew run`, listens on `127.0.0.1:8420`).

`bin/stx` runs the compiled Go client (`bin/stx-go`) and **builds it on first use**
(`go build -o bin/stx-go ./cmd/stx`), so you need **Go 1.26+** installed. Source: `cmd/stx` +
`internal/cli`.

```bash
./bin/stx ls                       # from the repo root (any CWD works)
ln -s "$PWD/bin/stx" ~/.local/bin/stx   # optional: put it on PATH
```

Daemon location: `--base-url` flag or `STX_URL` env (default `http://127.0.0.1:8420`).

## Stateless by design — always pass `-w`

There is **no stored "current workspace."** Every workspace-scoped command takes `-w <name|id>`
explicitly. This is intentional: multiple agents / concurrent sessions would clobber any shared or
env-based "current context" (and Claude Code's shell state doesn't even persist between calls).
Nothing is written to disk; each command fully self-describes. Workspace-keyed commands without a
resolvable `-w` exit non-zero with a hint. Commands keyed by a global id (`show`, `mv`, `edit`,
`done`, `archive`) don't need `-w`.

Add `--json` to any command for raw output (pipe to `jq`); the default is compact text.

## Composition — streams in, streams out, exit codes

Three conventions make `stx` usable *inside* a pipeline rather than only at the end of one.

**`-q` / `--quiet` — ids, one per line.** The pipe format: no padding, no glyphs, no
`(nothing ready)` placeholder. Every command prints the ids it produced or acted on; `meta get`
prints the bare value (strings unquoted) and `meta ls` the keys. Mutually exclusive with `--json`.

**`-` — read from stdin.** Anywhere an id or a text value is taken:

| Site | Commands |
|---|---|
| positional `<id>` | `show`, `mv`, `edit`, `done`, `block`/`unblock`, `relate`/`unrelate`, `archive` |
| `--desc` | `add`, `edit` |
| `meta set <key> <value>` | the value |

Id lines are read leniently — bare ids, `#41`, blank lines, `#`-comments, and even the padded
`next`/`tree` render all work (only the first field is parsed), so `stx next -w x | stx done -`
does what it looks like. Stdin is one stream: a second `-` in the same command is an error. A
batch keeps going past a failing id (xargs semantics), reporting each on stderr, and fails the
command at the end.

**Exit codes follow grep:**

| Code | Meaning |
|---|---|
| 0 | results |
| 1 | the command worked, its result set is empty (`ls`, `next`, `tree`, `meta ls`, `graph`, `status ls`, `relate-kinds`) |
| 2 | error — daemon down, bad id, illegal transition, conflict |

```bash
id=$(stx add "write migration" -w auth -t build -q)   # just the id
stx next -w auth -q | stx done -                      # finish everything ready
stx next -w auth -t build -q | stx block - --on "$id" # gate the frontier on one task
stx add "post-mortem" -w auth -t build --desc - < notes.md
stx meta set --task 42 config - < config.json         # raw JSON straight in
branch=$(stx meta get --task 42 branch -q)            # unquoted string

if stx next -w auth -q >/dev/null; then echo "work is ready"; else echo "all clear"; fi
```


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
    `--style <file>` (deep-merged over the base over built-in defaults); `--no-style` uses built-in
    defaults only. Every value is a **raw Graphviz attribute** passed through verbatim, so anything
    `dot` understands works. Config sections:
    | section | styles |
    |---------|--------|
    | `[workspace]` | the whole graph (bgcolor, fontname…) |
    | `[node]` / `[edge]` | default node / edge look |
    | `[status.<name>]` | task nodes by status name (case-insensitive) |
    | `[terminal]` | fallback for any terminal status with no `[status.*]` rule |
    | `[kind.<name>]` | task nodes by kind |
    | `[[priority]]` (`min` + `[priority.style]`) | task nodes at/above a priority (highest match wins) |
    | `[blocks]` / `[relates]` / `[relates_kind.<k>]` | edges |
    | `[track]` / `[track_name.<n>]`, `[segment]` / `[segment_name.<n>]` | clusters (see below) |

    A node layers `[node]` → kind → priority → terminal → status (later wins, attrs coexist), so a
    status fill and a kind border combine. Example:
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
    ```
    A full annotated config lives at [`examples/graph.toml`](../examples/graph.toml) — install it with
    `cp examples/graph.toml ~/.config/stx/graph.toml`.
  - **Clustering** (`--cluster none|track|segment`, default `none`): group task nodes into Graphviz
    clusters by track or by the nested segment tree; style clusters via `[track]`/`[track_name.<n>]`
    and `[segment]`/`[segment_name.<n>]`, and the whole graph via `[workspace]`.
  - **Demos:** `scripts/graph_demo.sh` (small graph, format/orientation) and
    `scripts/graph_bigdemo.sh` (a 13-task cross-track DAG in mixed statuses/kinds/priorities,
    rendered with `examples/graph.toml` in every cluster mode) each spin an isolated throwaway daemon
    and render into `build/`.
- **Containers/registries:** `ws new`, `track new`, `segment new`, `status …`, `kind …`, `transition`

Optimistic-lock versions are handled automatically by `mv`/`edit`/`done` (read-modify-write with one
retry on conflict). Illegal status moves print the legal targets.

## Editing in $EDITOR

Typing markdown into a shell argument is miserable, so `stx edit`, `stx add` and `stx meta set` can
hand the text to your editor. **The whole buffer is the description** — nothing is parsed or stripped, so `#` headings
survive byte-for-byte. The temp file is `stx-edit-<id>-*.md` (the `.md` gets you highlighting; the
id in the name is your "which task" cue in the editor's tab).

| Invocation | What happens |
|---|---|
| `stx edit 42` on a terminal, no field flags | opens the editor |
| `stx edit 42 -e` / `--editor` | forces it — works piped too, if the editor is a windowed one |
| `stx edit 42 --desc x` (any field flag) | flags win; the editor stays out of it |
| `stx edit 42` piped/scripted, no `-e` | `error: nothing to edit …` — scripts never hang |
| `stx next … -q \| stx edit - -e` | error: editor mode edits exactly one task |

`stx add "title" -w ws -t track -e` does the same for a new task, starting from an empty buffer —
but the editor is **never implied** there, because `stx add "quick note"` has to stay a one-liner.
`--desc` and `-e` are mutually exclusive.

`stx meta set --task 42 config -e` edits a metadata value. Two modes, matching how the value is read
back: by default the buffer is **pretty-printed JSON** (`.json`) and must still parse as JSON on
save — a typo becoming one enormous string would be a nasty surprise — while `--string` edits the
**raw text** (`.md`) and stores it verbatim, which is the sane way to write a long note. Pass a
value or `-e`, not both.

Save and close and the text is written (one trailing newline trimmed); close without touching it and
stx prints `unchanged #42` (or `unchanged <key>`) and writes nothing. An emptied buffer clears the description. If the
editor exits non-zero — or the daemon rejects the write — the temp file is **kept** and its path is
printed, so a long description is never lost.

**Which editor:** `$STX_EDITOR` → `$VISUAL` → `$EDITOR` → first of `zed`, `code`, `vi` on PATH.

GUI editors fork and return immediately unless told to wait, which would make every edit look
"unchanged", so stx adds the wait flag for editors it knows (`zed`, `code`, `code-insiders`,
`codium`, `cursor`, `subl`). Flags you typed yourself are never rewritten:

| Resolved value | Launched as |
|---|---|
| *(unset,* `zed` *on PATH)* | `zed -n -w <file>` — new window, blocks until you close it |
| `code` | `code -n -w <file>` |
| `code --wait` | `code --wait <file>` (you passed flags; only a missing wait is added) |
| `zed -w` | `zed -w <file>` |
| `vim` | `vim <file>` (terminal editor — never flagged, and requires a tty) |

A value containing shell metacharacters runs through `sh -c` verbatim, git-style, with no
auto-flagging. Set `STX_EDITOR` to take full control:

```bash
export STX_EDITOR="zed -n -w"      # or: code -n -w
```

```bash
stx edit 42                                  # description in a new zed window
stx add "write the RFC" -w auth -t build -e  # compose the description as you create the task
stx meta set --task 42 config -e             # edit the JSON value
stx meta set --task 42 notes -e --string     # edit a long note as raw text
```

## Interactive helpers

Two conveniences that surface live daemon data so you never hand-copy an id — both
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

Because those argument prompts are **single-line**, anywhere the answer is free text the builder
offers **`$EDITOR`** instead: `edit` asks "editor or fields?" up front, `add` lists
`$EDITOR (description)` among its optional extras, and `meta set` offers it in place of typing the
value. Picking it just adds `-e` to the assembled command, so what runs is a normal `stx …` you
could have typed.

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
