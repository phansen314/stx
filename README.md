# stx

A local **datastore + frontier server** for a developer and their local agents. You curate the
structure and context; an agent reads `next` for *what to work on* and reads task/track context for
*what to know*. The bar is "faster and more structured than a TODO.md" — not a JIRA replacement.

> **Status: v2 → v3 transition.** The **v3 Kotlin daemon** (`daemon/`) is the architecture going
> forward — a single-writer server clients reach over loopback HTTP. The **v2 Python CLI + TUI**
> (`src/stx`) is the current shipping interface; it still runs on the legacy workspace→group→task
> model and is **not yet wired to the daemon**. This README leads with v3; the v2 sections below
> document the Python app as it runs today.

## What it is (v3)

- **Datastore + frontier server** — a long-lived Kotlin daemon is the single writer; clients talk to
  it over loopback HTTP rather than opening SQLite directly.
- **Three-tier structure** — workspace → **track** (root-only line of work, carries context) →
  **segment** (pure-filing nesting) → **task** (the only first-class node).
- **Two edge graphs** — `blocks` (the spine: directed, acyclic, drives `next`) and `relates_to`
  (decorative association, cyclic OK, never affects the frontier).
- **`next` frontier** — a *filter*, not a recommender: returns the tasks you can act on now and makes
  no prioritization decision for you.
- **Self-defending store** — invariants enforced in SQLite + the daemon, so an agent writing to it
  cannot corrupt it.
- **No journal** — history is a non-authoritative append-only sidecar log; SQLite is the source of truth.

## Data Model (v3)

```
Workspace
├── Status            (per-workspace; status_transition defines legal moves; terminal == done)
└── Track             (root-only line of work; carries description + metadata)
    └── Segment       (pure filing; nests via parent_segment_id; one auto root segment per track)
        └── Task      (status, optional kind, description, metadata, priority, dates)
                      edges: blocks (DAG) / relates_to (decorative) — task↔task only
```

All entities support an `archived` flag (nothing is deleted; FKs never cascade).

## Architecture (v3)

```
clients ──▶ HTTP (127.0.0.1) ──▶ write-actor ──▶ Service ──▶ JDBC ──▶ SQLite (WAL)
                                       │
                                       └─▶ sidecar event log (append-only, non-authoritative)
```

Mutations are serialized through one write-actor coroutine; reads run concurrently against WAL.

## Daemon (v3) — Build & Run

```sh
cd daemon
./gradlew test            # 28 tests
./gradlew installDist
./build/install/stx-daemon/bin/stx-daemon --port=8473 --db=~/.local/share/stx/stx.db
```

Loopback-only is the security model — the daemon binds `127.0.0.1` and never an external interface.

**HTTP surface** (JSON responses; structured error envelope `{error, kind}` — Validation→400, NotFound→404, Conflict→409):

| Method & path | Purpose |
|---|---|
| `GET /next?workspace=&track=&segment=&kind=&limit=` | the frontier (ready set) |
| `GET /workspaces`, `/workspaces/{id}/statuses`, `/workspaces/{id}/tracks` | list |
| `GET /tracks/{id}/segments`, `/tracks/{id}/tasks?status=`, `/tasks/{id}` | list / detail |
| `POST /workspaces`, `/workspaces/{id}/statuses`, `/workspaces/{id}/transitions` | create |
| `POST /workspaces/{id}/tracks`, `/tracks/{id}/segments`, `/tracks/{id}/tasks` | create (track tasks route to the root segment) |
| `POST /tasks/{id}/status` | move status (rejects illegal transitions) |
| `PATCH /tasks/{id}` | edit title/desc/priority/kind/dates/metadata |
| `POST /blocks`, `/relates` | add edges (`blocks` is DAG-checked) |
| `POST /{tasks,tracks,segments,statuses,workspaces}/{id}/archive` | archive (cascades incident edges) |

Authoritative design: `daemon/docs/stx-v3-{design,next,implementation-brief}.md`; schema:
`daemon/src/main/resources/schema.sql`. One-page overview + ERD: [`docs/v3-architecture.md`](docs/v3-architecture.md).

---

# v2 Python CLI & TUI (current implementation)

The sections below document the **v2** Python app under `src/stx` — the interface users run today.
It uses the legacy workspace → group → task model and is **not yet wired to the v3 daemon**.

## Quick Start

```sh
# Install in editable mode
pip install -e .

# Create a workspace with statuses
stx workspace create ops --statuses "Backlog","Active","Done"

# Build structure (path-as-title creates nested groups in one step)
stx group create "infra" --desc "Infrastructure work"
stx group create "infra/Q2 Migrations"
stx group create "infra/Q2 Migrations/Postgres"

# Attach context as metadata
stx group meta set "infra" owner "platform-team"
stx group meta set "infra/Q2 Migrations/Postgres" estimate "3 sprints"

# Tasks live inside the structure (path refs disambiguate any collision)
stx task create "Upgrade to PG 16" -S Backlog -g "infra/Q2 Migrations/Postgres"
stx task create "Load test new cluster" -S Backlog -g "infra/Q2 Migrations/Postgres"
stx edge create --source task-0002 --target task-0001 --kind blocks

# View it
stx tui
```

## Modeling Context

stx earns its keep before any task is created. The hierarchy — workspaces, nested groups, metadata, descriptions — is where context lives.

```sh
# Model nested structure — `/` is the group-path delimiter, anchored at root
stx group create "API Rewrite" --desc "Migrate from REST to GraphQL"
stx group create "API Rewrite/Auth" --desc "Token and session handling"
stx group create "API Rewrite/Auth/OAuth"
stx group create "API Rewrite/Auth/Session"

# Attach structured metadata at each level
stx group meta set "API Rewrite" deadline "2026-06-01"
stx group meta set "API Rewrite" owner "backend-team"
stx group meta set "API Rewrite/Auth/OAuth" provider "Auth0"

# Export full context as JSON for agent consumption
stx workspace show | jq
stx export --md > context.md
```

## CLI

Entry point: `stx`

**The CLI is the primary interface for agents.** Output auto-switches to JSON when piped, making every command composable in agent workflows. Override with `--json` (force JSON) or `--text` (force text). See [`skills/stx/references/json-schema.md`](skills/stx/references/json-schema.md) for per-command shapes.

**Active workspace:** Stored in `~/.config/stx/tui.toml`. Set via `stx workspace use <name>` or `stx config set active_workspace <name>`. Override per-command with `--workspace`/`-w`.

### Structure Commands

| Command | Description |
|---------|-------------|
| `stx workspace ...` | `create [--statuses a,b,c]`, `ls`, `show`, `use`, `edit [--name]`, `archive [--force\|--dry-run]`, `meta ls\|get\|set\|del` |
| `stx group ...` | `create [--parent <group-path>] [--desc]`, `ls`, `show`, `edit [--title] [--desc]`, `archive [--force\|--dry-run]`, `mv`, `assign`, `unassign`, `meta ls\|get\|set\|del <title-or-path>` (edges live under top-level `stx edge`). All group args accept path syntax (`A/B/C`); `group create A/B/new` creates `new` under the existing parent path `A/B` (mutex with `--parent`). |

### Task Commands

| Command | Description |
|---------|-------------|
| `stx task create <title> -S <status>` | Create a task in the named status (required); accepts `--group/-g` |
| `stx task ls` | List tasks on the active workspace |
| `stx task show <task>` | Show task detail with history, edges, and metadata |
| `stx task edit <task>` | Edit task fields (`--title`, `--desc`, `--priority`, `--due`) |
| `stx task mv <task> -S <status> [pos]` | Move task to a status (within-workspace only) |
| `stx task done <task>` | Mark a task done (independent of status; sticky; no-op if already done) |
| `stx task undone <task> [--force]` | Clear the done flag (requires `--force` in non-interactive stdin) |
| `stx task archive <task> [--force] [--dry-run]` | Archive a task (with confirmation) |
| `stx task log <task>` | Show task change history |
| `stx task meta ls\|get\|set\|del <task> ...` | Key/value metadata CRUD (workspaces and groups expose the same four verbs) |

Task identifiers are auto-detected: numeric forms (`1`, `task-0001`, `#1`) resolve as IDs; bare strings are looked up as a title on the active workspace; path forms (`A/B:leaf`, `:rootleaf`) walk a group path then locate the leaf task. Group references use the same syntax: bare `A` (workspace-wide), `/A` (root group `A` — leading-slash anchor), or `A/B/C` (nested path). `/` and `:` are reserved for path syntax and forbidden in group/task titles.

### Task Filters

`stx task ls` supports filtering:

| Flag | Description |
|------|-------------|
| `--archived {hide,include,only}` | Archived visibility (default `hide`) |
| `--status` / `-S` | Filter by status name |
| `--priority` | Filter by priority integer |
| `--search` | Search by title substring |
| `--group` / `-g` | Filter by group title or path (e.g. `A/B/C`); flat — does not include subgroups |

### Workflow Commands

| Command | Description |
|---------|-------------|
| `stx status ...` | `create`, `ls`, `show`, `edit [--name] [--terminal\|--no-terminal]`, `order <statuses...>`, `archive [--reassign-to STATUS\|--force]`. `--terminal` marks a status so tasks moved into it auto-set `done=true`. |
| `stx edge ...` | `create --source <t> --target <t> --kind <k>`, `archive --source <t> --target <t>`, `ls [--source <t>] [--kind <k>]`, `meta ls\|get\|set\|del --source <t> --target <t>` |
| `stx next [--rank] [--limit N] [--include-blocked] [--edge-kind KIND]` | Topo-sort the acyclic `blocks` DAG to surface the actionable task frontier and the blocked list with pending blocker IDs |
| `stx graph [--format dot\|mermaid] [--kind KIND ...] [--output PATH]` | Generate a DOT or Mermaid graph file from workspace edges. `--kind` is repeatable to include multiple edge kinds. Writes a temp file if no `--output` given. To view DOT files: `sudo apt install xdot && xdot graph.dot`, or render to PNG with `dot -Tpng graph.dot -o graph.png` (requires `graphviz`). For Mermaid, paste into [mermaid.live](https://mermaid.live). |
| `stx export` | Export database as JSON (default) or Markdown with Mermaid edge graphs labelled by `kind` (`--md`) |
| `stx info` | Show stx file locations |
| `stx backup <dest>` | Atomic binary DB snapshot (safe pre-migration backup) |

### Cross-Workspace Transfer

Tasks can be transferred between workspaces. The transfer creates a copy on the target workspace and archives the original. Active edges must be archived first (`stx edge archive --source … --target …`).

```sh
# Transfer task to another workspace
stx task transfer task-0001 --to ops --status Backlog

# Preview before transferring (checks for blocking edges)
stx task transfer task-0001 --to ops --status Backlog --dry-run
```

## Hooks

Run shell commands on any stx mutation. Hooks are post-commit observers — the write always proceeds; hooks observe committed state and are fire-and-forget. Each hook receives a JSON payload on stdin describing the event.

Config lives at `~/.config/stx/hooks.toml`. Commands execute via `shell=True` — trust model matches git hooks (anyone who can write the file can run arbitrary code as you).

```toml
# ~/.config/stx/hooks.toml

# Desktop notification when a task is marked done.
[[hooks]]
event = "task.done"
timing = "post"
name = "notify-done"
command = '''jq -r '"✓ " + .entity.title + " done"' | xargs -I{} notify-send "stx" "{}"'''

# JSONL audit log for every task update.
[[hooks]]
event = "task.updated"
timing = "post"
name = "audit-log"
command = "jq -c '{ts: now|strftime(\"%FT%T\"), event, entity: .entity.title, changes}' >> ~/.local/share/stx/activity.jsonl"
```

Discoverability:

```sh
stx hook events                      # list all 29 valid events
stx hook ls                          # list configured hooks (filters: --event --timing --workspace)
stx hook validate                    # schema-check hooks.toml (exit 4 if invalid)
stx hook schema                      # print the full JSON Schema
```

See [`skills/stx/references/hooks.md`](skills/stx/references/hooks.md) for the full event catalog, payload shapes, recipe library, and gotchas.

## TUI

Launch with `stx tui` (or `stx tui --db path/to/db`).

The TUI is designed for human interaction alongside agent-driven CLI usage. The left panel shows the full context hierarchy (workspaces, groups, tasks); the right panel renders tasks as a kanban board — one scrollable column per status.

For development with live reload and the Textual dev console:

```sh
textual run --dev stx.tui.app:StxApp
```

- **Layout**: Two-panel split — workspace hierarchy tree (left, 25%) and kanban board with one scrollable column per status (right). Diff-based kanban sync with coalescing refresh.
- **Edit modals**: Press `e` on any tree node or kanban card to edit tasks, groups, or workspaces. Full form with validation, Markdown description editor, and change diffing. The task modal has a Group selector showing all unarchived workspace groups.
- **Metadata editor**: Press `m` on any tree node (task, workspace, group) or kanban card to view/edit the entity's key/value metadata. Dynamic rows with add/delete, client-side duplicate-key detection, and bulk-replace on save.
- **Create modals**: Press `n` to open a resource type selector and create tasks, groups, statuses, or workspaces. The status-create modal defaults the workspace selector to the currently active workspace.
- **Workspace switching**: Press `s` to switch between workspaces.
- **Config**: `~/.config/stx/tui.toml` (theme, show_archived, confirm_archive, default_priority, status_order, auto_refresh_seconds)

**Keybindings:**

| Key | Action |
|-----|--------|
| `w` | Focus workspace tree |
| `b` | Focus kanban board |
| `r` | Refresh |
| `e` | Edit selected entity |
| `m` | Edit metadata on selected entity |
| `g` | Generate DOT graph of workspace edges (prints temp file path) |
| `c` | Open settings modal (theme, auto_refresh_seconds) |
| `n` | Create new (task/group/status/workspace selector) |
| `s` | Switch workspace |
| `[` / `]` / `shift+left` / `shift+right` | With a task card focused: move task left/right across statuses. With a status column focused: reorder the column (persists to `tui.toml`). |
| `ctrl+q` | Quit |

## Claude Code Plugin

The repo ships a Claude Code plugin that exposes the `stx` CLI as a model-invoked skill. Claude auto-triggers on context management and task-tracking intent and constructs `stx` commands directly.

### Development / testing

Load the plugin directly from your local clone:

```bash
claude --plugin-dir /path/to/stx
```

After editing skill/hook/command files, run `/reload-plugins` in-session to pick up changes — no restart or `version` bump needed.

### Permanent install

Add this repo as a marketplace, then install the plugin:

```
/plugin marketplace add phansen314/stx
/plugin install stx@stx
```

### Updating

Pull the latest published version:

```
/plugin update stx@stx
```

Updates are gated on the `version` field in `.claude-plugin/plugin.json` — users won't see new commits until the author bumps the version and pushes.

If `stx` is not found, the skill will ask how you'd like to install it. Install the CLI with `pip install -e .` (see Quick Start) or directly from GitHub:

```sh
pip install git+https://github.com/phansen314/stx.git
```

## Workflow Tracking (manual setup)

If you prefer not to install the plugin, seed a workspace and paste the workflow snippet into your `~/.claude/CLAUDE.md`:

```sh
stx workspace create claude --statuses Backlog,"In Progress",Done
```

```markdown
## Workflow Tracking with stx

For multi-step plans (5+ steps), use the `stx` CLI to track progress persistently.
All work lives on the **"claude" workspace** which has three statuses: Backlog, In Progress, Done.

1. Switch to the claude workspace: `stx workspace use claude`
2. Create a group for the plan: `stx group create "<plan name>"`
3. Create one task per plan step: `stx task create "<step>" -S Backlog -g "<plan>" -P N`
4. Add edges where ordering matters: `stx edge create --source task-NNNN --target task-MMMM --kind blocks`
5. Move tasks to "In Progress" when starting: `stx task mv task-NNNN "In Progress"`
6. Mark tasks done when complete: `stx task mv task-NNNN Done`
7. Run `stx export` at milestones for a full status snapshot
```

## Requirements

**v2 Python CLI/TUI:**
- Python 3.12+
- [Textual](https://textual.textualize.io/) (TUI)

Dev dependencies: pytest, pytest-cov

```sh
pip install -e ".[dev]"
```

**v3 daemon:** JDK 21+ and Gradle (via the wrapper in `daemon/`). No Python needed for the daemon.

## Data Storage

Database path: `~/.local/share/stx/stx.db` (XDG-compliant, WAL journal mode)

To generate an ER diagram from the schema:

```sh
python scripts/generate_erd.py
```

## Testing

**v2 Python:**

```sh
pytest
pytest --cov
```

Fresh in-memory DB per test — no cross-test pollution. TUI tests use Textual's `app.run_test()` pilot API.

**v3 daemon:**

```sh
cd daemon && ./gradlew test    # 28 tests: schema, the 5 invariants, frontier + rework, write-actor, sidecar, HTTP e2e
```

For manual TUI testing with seeded data:

```sh
python tests/seed.py tmp/test.db
stx tui --db tmp/test.db
```

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for release notes. Release process is documented in [RELEASING.md](RELEASING.md).
