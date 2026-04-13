# stx

Organize context into nestable hierarchies of workspaces, projects, and groups. Track tasks across them. CLI speaks JSON for agents; TUI shows a kanban board for humans.

## What it is

- **Structured context, not just tasks** — the primary unit is the hierarchy itself: workspaces, projects, and recursively nestable groups (Group → Group → … via `parent_id`).
- **Metadata everywhere** — every node (workspace, project, group, task) carries a JSON key/value blob (`stx {entity} meta set/get/del`) and an optional long-form description on projects, groups, and tasks (rendered as Markdown in the TUI).
- **Task management** — tasks have statuses, priorities, dates, tags, kinded edges, and positions. Statuses are user-defined per workspace — kanban columns are just one interpretation.
- **Kinded edge graphs** — tasks link to tasks and groups link to groups via labelled edges (`stx edge`, `stx group edge`). Each edge carries a `kind` label and its own metadata blob. Mermaid diagrams generated on export.
- **Agent-first CLI** — output auto-switches to JSON when piped (`stx task ls | jq`). Every command is composable without screen-scraping.
- **Human-friendly TUI** — renders the hierarchy as a kanban board. The left panel shows the full workspace tree; the right panel shows one column per status.
- **Full audit trail** — field changes across all entities (tasks, projects, groups, workspaces, statuses), edge link/unlink events (task and group), and per-key metadata diffs are recorded in a unified `journal` table with old/new values and a source tag. Cross-entity timeline queries work without JOINs.
- **SQLite-backed** — WAL journal mode, XDG paths, atomic backups, numbered migrations.

## Data Model

```
Workspace
├── Status  (workflow stages, user-defined)
├── Tag  ↔  Task  (many-to-many, workspace-scoped)
├── Project
│   ├── Group
│   │   ├── Group  (nested, no depth limit)
│   │   │   └── Task
│   │   └── Task
│   └── Task  (ungrouped)
└── Task  (no project)
```

All entities support:
- `archived` flag (nothing is deleted)
- `metadata` — JSON key/value blob, keys normalized to lowercase

Projects, groups, and tasks additionally support `description` (free-text, Markdown).

Tasks additionally have: priority, due/start/finish dates, position, tags, kinded edges (`edge_sources` / `edge_targets`, each carrying a `kind` label and its own metadata blob), and change history.

Groups additionally have: `parent_id` (recursive nesting), position, and kinded edges.

## Architecture

```
CLI commands ────────┐
TUI event handlers ──┤──▶ Service ──▶ Repository ──▶ Connection ──▶ SQLite
```

## Quick Start

```sh
# Install in editable mode
pip install -e .

# Create a workspace with statuses
stx workspace create ops --statuses "Backlog","Active","Done"

# Build structure
stx project create infra --desc "Infrastructure projects"
stx group create "Q2 Migrations" --project infra
stx group create "Postgres" --project infra --parent "Q2 Migrations"

# Attach context as metadata
stx project meta set infra owner "platform-team"
stx group meta set "Postgres" estimate "3 sprints" --project infra

# Tasks live inside the structure
stx task create "Upgrade to PG 16" -S Backlog --project infra -g "Postgres"
stx task create "Load test new cluster" -S Backlog --project infra -g "Postgres"
stx edge create --source task-0002 --target task-0001 --kind blocks

# View it
stx tui
```

## Modeling Context

stx earns its keep before any task is created. The hierarchy — workspaces, projects, nested groups, metadata, descriptions — is where context lives.

```sh
# Model a project with nested structure
stx project create "API Rewrite" --desc "Migrate from REST to GraphQL"
stx group create "Auth" --project "API Rewrite" --desc "Token and session handling"
stx group create "OAuth" --project "API Rewrite" --parent "Auth"
stx group create "Session" --project "API Rewrite" --parent "Auth"

# Attach structured metadata at each level
stx project meta set "API Rewrite" deadline "2026-06-01"
stx project meta set "API Rewrite" owner "backend-team"
stx group meta set "OAuth" provider "Auth0" --project "API Rewrite"

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
| `stx workspace ...` | `create [--statuses a,b,c]`, `ls`, `show`, `use`, `rename`, `archive [--force\|--dry-run]`, `meta ls\|get\|set\|del` |
| `stx project ...` | `create [--desc]`, `ls`, `show`, `edit [--desc]`, `rename`, `archive [--force\|--dry-run]`, `meta ls\|get\|set\|del <name>` |
| `stx group ...` | `create [--desc]`, `ls`, `show`, `rename`, `edit [--desc]`, `archive [--force\|--dry-run]`, `mv`, `assign`, `unassign`, `edge create\|archive\|ls\|meta *`, `meta ls\|get\|set\|del <title> [--project]` |

### Task Commands

| Command | Description |
|---------|-------------|
| `stx task create <title> -S <status>` | Create a task in the named status (required); accepts `--group/-g` |
| `stx task ls` | List tasks on the active workspace |
| `stx task show <task>` | Show task detail with history, edges, and metadata |
| `stx task edit <task>` | Edit task fields (`--title`, `--desc`, `--priority`, `--due`, `--project`) |
| `stx task mv <task> -S <status> [pos]` | Move task to a status (within-workspace only) |
| `stx task archive <task> [--force] [--dry-run]` | Archive a task (with confirmation) |
| `stx task log <task>` | Show task change history |
| `stx task meta ls\|get\|set\|del <task> ...` | Key/value metadata CRUD (workspaces, projects, and groups expose the same four verbs) |

Task identifiers are auto-detected: numeric forms (`1`, `task-0001`, `#1`) resolve as IDs; anything else is looked up as a title on the active workspace.

### Task Filters

`stx task ls` supports filtering:

| Flag | Description |
|------|-------------|
| `--archived {hide,include,only}` | Archived visibility (default `hide`) |
| `--status` / `-S` | Filter by status name |
| `--project` / `-p` | Filter by project name |
| `--priority` | Filter by priority integer |
| `--search` | Search by title substring |
| `--group` / `-g` | Filter by group title |
| `--tag` / `-t` | Filter by tag name |

### Workflow Commands

| Command | Description |
|---------|-------------|
| `stx status ...` | `create`, `ls`, `rename`, `order <workspace> <statuses...>`, `archive [--reassign-to STATUS\|--force]` |
| `stx edge ...` | `create --source <t> --target <t> --kind <k>`, `archive --source <t> --target <t>`, `ls [--source <t>] [--kind <k>]`, `meta ls\|get\|set\|del --source <t> --target <t>` |
| `stx tag ...` | `create`, `ls`, `rename`, `archive [--unassign\|--force\|--dry-run]` |
| `stx export` | Export database as JSON (default) or Markdown with Mermaid edge graphs labelled by `kind` (`--md`) |
| `stx info` | Show stx file locations |
| `stx backup <dest>` | Atomic binary DB snapshot (safe pre-migration backup) |

### Cross-Workspace Transfer

Tasks can be transferred between workspaces. The transfer creates a copy on the target workspace and archives the original. Active edges must be archived first (`stx edge archive --source … --target …`).

```sh
# Transfer task to another workspace
stx task transfer task-0001 --to ops --status Backlog

# Transfer with project assignment on the target workspace
stx task transfer task-0001 --to ops --status Backlog --project infra

# Preview before transferring (checks for blocking edges)
stx task transfer task-0001 --to ops --status Backlog --dry-run
```

## TUI

Launch with `stx tui` (or `stx tui --db path/to/db`).

The TUI is designed for human interaction alongside agent-driven CLI usage. The left panel shows the full context hierarchy (workspaces, projects, groups, tasks); the right panel renders tasks as a kanban board — one scrollable column per status.

For development with live reload and the Textual dev console:

```sh
textual run --dev stx.tui.app:StxApp
```

- **Layout**: Two-panel split — workspace hierarchy tree (left, 25%) and kanban board with one scrollable column per status (right). Diff-based kanban sync with coalescing refresh.
- **Edit modals**: Press `e` on any tree node or kanban card to edit tasks, projects, groups, or workspaces. Full form with validation, Markdown description editor, and change diffing. The task modal has a Group selector that filters by the selected Project and updates reactively.
- **Metadata editor**: Press `m` on any tree node (task, workspace, project, group) or kanban card to view/edit the entity's key/value metadata. Dynamic rows with add/delete, client-side duplicate-key detection, and bulk-replace on save.
- **Create modals**: Press `n` to open a resource type selector and create tasks, groups, projects, statuses, or workspaces. The task-create modal exposes the same project-scoped Group selector. The status-create modal defaults the workspace selector to the currently active workspace.
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
| `c` | Open settings modal (theme, auto_refresh_seconds) |
| `n` | Create new (task/group/project/status/workspace selector) |
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
2. Create a project for the plan: `stx project create "<plan name>"`
3. Create one task per plan step: `stx task create "<step>" -S Backlog --project "<plan>" -P N`
4. Add edges where ordering matters: `stx edge create --source task-NNNN --target task-MMMM --kind blocks`
5. Move tasks to "In Progress" when starting: `stx task mv task-NNNN "In Progress"`
6. Mark tasks done when complete: `stx task mv task-NNNN Done`
7. Run `stx export` at milestones for a full status snapshot
```

## Requirements

- Python 3.12+
- [Textual](https://textual.textualize.io/) (TUI)

Dev dependencies: pytest, pytest-cov

```sh
pip install -e ".[dev]"
```

## Data Storage

Database path: `~/.local/share/stx/stx.db` (XDG-compliant, WAL journal mode)

To generate an ER diagram from the schema:

```sh
python scripts/generate_erd.py
```

## Testing

```sh
pytest
pytest --cov
```

Fresh in-memory DB per test — no cross-test pollution. TUI tests use Textual's `app.run_test()` pilot API.

For manual TUI testing with seeded data:

```sh
python tests/seed.py tmp/test.db
stx tui --db tmp/test.db
```

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for release notes. Release process is documented in [RELEASING.md](RELEASING.md).
