# sticky-notes

A local todo/kanban app with two interfaces:

- **CLI** (argparse) — task management from the terminal, with `--json` for structured output
- **TUI** (Textual) — interactive kanban board with keyboard navigation

All interfaces share the same database and service layer, backed by **SQLite**.

## Architecture

```
CLI commands ────────┐
TUI event handlers ──┤──▶ Service ──▶ Repository ──▶ Connection ──▶ SQLite
```

## Quick Start

```sh
# Install in editable mode
pip install -e .

# Create a workspace with seed statuses
todo workspace create work --statuses "To Do","In Progress","Done"

# Add and manage tasks
todo task create "Write README" -S "To Do"
todo task ls
todo task mv task-0001 -S "In Progress"
todo task mv task-0001 -S "Done"

# Launch the TUI
todo tui
```

## CLI Usage

Entry point: `todo`

**Active workspace:** The CLI tracks the active workspace in `~/.local/share/sticky-notes/active-workspace`. Override per-command with `--workspace`/`-w`.

**JSON output:** Add `--json` before any command for structured JSON output.

### Task Commands

| Command | Description |
|---------|-------------|
| `todo task create <title> -S <status>` | Create a task in the named status (required); accepts `--group/-g` |
| `todo task ls` | List tasks on the active workspace |
| `todo task show <task>` | Show task detail with history, dependencies, and metadata |
| `todo task edit <task>` | Edit task fields (`--title`, `--desc`, `--priority`, `--due`, `--project`) |
| `todo task mv <task> -S <status> [pos]` | Move task to a status (within-workspace only) |
| `todo task archive <task> [--force] [--dry-run]` | Archive a task (with confirmation) |
| `todo task log <task>` | Show task change history |
| `todo task meta ls\|get\|set\|del <task> ...` | JSON key/value metadata CRUD (lowercase-normalized keys; workspaces, projects, and groups expose the same four verbs) |

Task identifiers are auto-detected: numeric forms (`1`, `task-0001`, `#1`) resolve as IDs; anything else is looked up as a title on the active workspace.

### List Filters

`todo task ls` supports filtering:

| Flag | Description |
|------|-------------|
| `--archived {hide,include,only}` | Archived visibility (default `hide`) |
| `--status` / `-S` | Filter by status name |
| `--project` / `-p` | Filter by project name |
| `--priority` | Filter by priority (1-5) |
| `--search` | Search by title substring |
| `--group` / `-g` | Filter by group title |
| `--tag` / `-t` | Filter by tag name |

### Management Commands

| Command | Description |
|---------|-------------|
| `todo workspace ...` | `create [--statuses a,b,c]`, `ls`, `use`, `rename`, `archive [--force\|--dry-run]`, `meta ls\|get\|set\|del` |
| `todo status ...` | `create`, `ls`, `rename`, `order <workspace> <statuses...>`, `archive [--reassign-to STATUS\|--force]` |
| `todo project ...` | `create [--desc]`, `ls`, `show`, `edit [--desc]`, `rename`, `archive [--force\|--dry-run]`, `meta ls\|get\|set\|del <name>` |
| `todo dep ...` | `create`, `archive` |
| `todo tag ...` | `create`, `ls`, `rename`, `archive [--unassign\|--force\|--dry-run]` |
| `todo group ...` | `create [--desc]`, `ls [--tree]`, `show`, `rename`, `edit [--desc]`, `archive [--force\|--dry-run]`, `mv`, `assign`, `unassign`, `dep create\|archive`, `meta ls\|get\|set\|del <title> [--project]` |
| `todo context` | One-call workspace summary: statuses, tasks, projects, tags, groups |
| `todo export` | Export database as JSON (default) or Markdown (`--md`) |
| `todo info` | Show sticky-notes file locations |
| `todo backup <dest>` | Atomic binary DB snapshot (safe pre-migration backup) |

### Cross-Workspace Transfer

Tasks can be transferred between workspaces. The transfer creates a copy on the target workspace and archives the original. Dependencies must be removed first.

```sh
# Transfer task to another workspace
todo task transfer task-0001 --to ops --status Backlog

# Transfer with project assignment on the target workspace
todo task transfer task-0001 --to ops --status Backlog --project infra

# Preview before transferring (checks for blocking dependencies)
todo task transfer task-0001 --to ops --status Backlog --dry-run
```

## TUI

Launch with `todo tui` (or `todo tui --db path/to/db`).

For development with live reload and the Textual dev console:

```sh
textual run --dev sticky_notes.tui.app:StickyNotesApp
```

- **Layout**: Two-panel split — workspace hierarchy tree (left, 25%) and kanban board with one scrollable column per status (right). Diff-based kanban sync with coalescing refresh.
- **Edit modals**: Press `e` on any tree node or kanban card to edit tasks, projects, groups, or workspaces. Full form with validation, markdown description editor, and change diffing. The task modal has a Group selector that filters by the selected Project and updates reactively.
- **Metadata editor**: Press `m` on any tree node (task, workspace, project, group) or kanban card to view/edit the entity's JSON key/value metadata blob. Dynamic rows with add/delete, client-side duplicate-key detection, and bulk-replace on save via `service.replace_*_metadata`.
- **Create modals**: Press `n` to create new tasks, projects, or groups via a resource type selector. The task-create modal exposes the same project-scoped Group selector.
- **Workspace switching**: Press `s` to switch between workspaces.
- **Config**: `~/.config/sticky-notes/tui.toml` (theme, show_archived, confirm_archive, default_priority, status_order, auto_refresh_seconds)

**Keybindings:**

| Key | Action |
|-----|--------|
| `w` | Focus workspace tree |
| `b` | Focus kanban board |
| `r` | Refresh |
| `e` | Edit selected entity |
| `m` | Edit metadata on selected entity |
| `n` | Create new (task/group/project) |
| `s` | Switch workspace |
| `[` / `]` | Move task left/right across statuses |
| `ctrl+q` | Quit |

## Claude Code Plugin

The repo ships a Claude Code plugin that exposes the `todo` CLI as a model-invoked skill. Claude auto-triggers on task/kanban/plan-tracking intent and constructs `todo` commands directly.

### Development / testing

Load the plugin directly from your local clone:

```bash
claude --plugin-dir /path/to/sticky-notes
```

After editing skill/hook/command files, run `/reload-plugins` in-session to pick up changes — no restart or `version` bump needed.

### Permanent install

Add this repo as a marketplace, then install the plugin:

```
/plugin marketplace add phansen314/sticky-notes
/plugin install sticky-notes@sticky-notes
```

### Updating

Pull the latest published version:

```
/plugin update sticky-notes@sticky-notes
```

Updates are gated on the `version` field in `.claude-plugin/plugin.json` — users won't see new commits until the author bumps the version and pushes.

If `todo` is not found, the skill will ask how you'd like to install it. Install the CLI with `pip install -e .` (see Quick Start) or directly from GitHub:

```sh
pip install git+https://github.com/phansen314/sticky-notes.git
```

## Workflow Tracking (manual setup)

If you prefer not to install the plugin, seed a workspace and paste the workflow snippet into your `~/.claude/CLAUDE.md`:

```sh
todo workspace create claude --statuses Backlog,"In Progress",Done
```

```markdown
## Workflow Tracking with sticky-notes

For multi-step plans (5+ steps), use the `todo` CLI to track progress persistently.
All work lives on the **"claude" workspace** which has three statuses: Backlog, In Progress, Done.

1. Switch to the claude workspace: `todo workspace use claude`
2. Create a project for the plan: `todo project create "<plan name>"`
3. Create one task per plan step: `todo task create "<step>" -S Backlog --project "<plan>" -P N`
4. Add dependencies where ordering matters: `todo dep create task-NNNN task-MMMM`
5. Move tasks to "In Progress" when starting: `todo task mv task-NNNN "In Progress"`
6. Mark tasks done when complete: `todo task mv task-NNNN Done`
7. Run `todo export` at milestones for a full status snapshot
```

## Data Model

**Hierarchy:** Workspace → Status → Task (and Workspace → Project → Task)

Statuses are workspace-scoped and represent kanban workflow stages. No data is ever deleted — use `archived` flags instead. All mutations are recorded in the task history audit trail.

To generate an ER diagram from the schema:

```sh
python scripts/generate_erd.py
```

This parses `schema.sql` and outputs a Mermaid diagram to stdout. Pipe to a file if needed:

```sh
python scripts/generate_erd.py > erd.mermaid
```

## Requirements

- Python 3.12+
- [Textual](https://textual.textualize.io/) (TUI)

Dev dependencies: pytest, pytest-cov

```sh
pip install -e ".[dev]"
```

## Data Storage

Database path: `~/.local/share/sticky-notes/sticky-notes.db` (XDG-compliant, WAL journal mode)

## Testing

```sh
pytest
pytest --cov
```

Fresh in-memory DB per test — no cross-test pollution. TUI tests use Textual's `app.run_test()` pilot API.

For manual TUI testing with seeded data:

```sh
python tests/seed.py tmp/test.db
todo tui --db tmp/test.db
```

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for release notes. Release process is documented in [RELEASING.md](RELEASING.md).
