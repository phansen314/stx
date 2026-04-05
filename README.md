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

# Create a board with seed columns
todo board create work --columns "To Do","In Progress","Done"

# Add and manage tasks
todo create "Write README" -c "To Do"
todo ls
todo mv task-0001 "In Progress"
todo mv task-0001 "Done"

# Launch the TUI
todo tui
```

## CLI Usage

Entry point: `todo`

**Active board:** The CLI tracks the active board in `~/.local/share/sticky-notes/active-board`. Override per-command with `--board`/`-b`.

**JSON output:** Add `--json` before any command for structured JSON output.

### Task Commands

| Command | Description |
|---------|-------------|
| `todo create <title> -c <col>` | Create a task in the named column (required) |
| `todo ls` | List tasks on the active board |
| `todo show <task>` | Show task detail with history and dependencies |
| `todo edit <task>` | Edit task fields (`--title`, `--desc`, `--priority`, `--due`, `--project`) |
| `todo mv <task> <column> [pos]` | Move task to a column (within-board only) |
| `todo rm <task>` | Archive a task |
| `todo log <task>` | Show task change history |

Use `--by-title` on any task command to resolve `<task>` by title string instead of ID.

### List Filters

`todo ls` supports filtering:

| Flag | Description |
|------|-------------|
| `--all` / `-a` | Include archived tasks |
| `--archived` | Show only archived tasks |
| `--column` / `-c` | Filter by column name |
| `--project` / `-p` | Filter by project name |
| `--priority` / `-P` | Filter by priority (1-5) |
| `--search` / `-s` | Search by title substring |

### Management Commands

| Command | Description |
|---------|-------------|
| `todo board ...` | `create [--columns a,b,c]`, `ls`, `use`, `rename`, `rm` |
| `todo col ...` | `create`, `ls`, `rename`, `rm [--reassign-to COL\|--force]` |
| `todo project ...` | `create`, `ls`, `show`, `rm` |
| `todo dep ...` | `create`, `rm` |
| `todo tag ...` | `create`, `ls`, `rm [--unassign]` |
| `todo group ...` | `create`, `ls [--tree]`, `show`, `rename`, `rm`, `mv`, `assign`, `unassign` |
| `todo export` | Export database to Markdown with Mermaid dependency graphs |

### Cross-Board Transfer

Tasks can be transferred between boards. The transfer creates a copy on the target board and archives the original. Dependencies must be removed first.

```sh
# Transfer task to another board
todo transfer task-0001 --board ops --column Backlog

# Transfer with project assignment on the target board
todo transfer task-0001 --board ops --column Backlog --project infra

# Preview before transferring (checks for blocking dependencies)
todo transfer task-0001 --board ops --column Backlog --dry-run
```

## TUI

Launch with `todo tui` (or `todo tui --db path/to/db`).

The TUI provides a full kanban board view with keyboard-driven navigation and modal dialogs.

### Keybindings

| Key | Action |
|-----|--------|
| Arrow keys | Navigate between tasks and columns |
| `Enter` | Open task detail (read-only) |
| `e` | Edit task |
| `n` | Create new task in focused column |
| `m` | Move task to a different board |
| `d` / `Delete` | Archive task |
| `Shift+Left/Right` | Move task between columns |
| `s` | Open settings |
| `a` | Open all-tasks view |
| `b` | Switch board |
| `p` | Filter by project |
| `c` | Filter by column (in all-tasks view) |

### Settings

Accessible via `s` key. Stored at `~/.config/sticky-notes/tui.toml`.

- **Theme**: dark/light
- **Show archived**: toggle archived task visibility
- **Show task descriptions**: toggle description display on cards
- **Confirm archive**: prompt before archiving
- **Default priority**: 1-5 for new tasks
- **Auto-refresh**: configurable interval (off, 15s, 30s, 60s, 120s)

### Screens

- **Board View** — main kanban grid with columns and task cards
- **All Tasks** — flat list of all tasks with column filtering
- **Settings** — theme, display, and behavior preferences
- **Task Detail** — read-only task view with history (press `e` to edit from here)
- **Task Form** — create/edit task modal with validation
- **Move to Board** — select target board, column, and optional project

## Claude Code Integration

The `todo` CLI can be used by Claude Code to persistently track multi-step plans. Use the `/todo` command for the full CLI reference.

Setup:

```sh
todo board create claude --columns Backlog,"In Progress",Done
```

Then add to your `~/.claude/CLAUDE.md`:

```markdown
## Workflow Tracking with sticky-notes

For multi-step plans (5+ steps), use the `todo` CLI to track progress persistently.
All work lives on the **"claude" board** which has three columns: Backlog, In Progress, Done.

1. Switch to the claude board: `todo board use claude`
2. Create a project for the plan: `todo project create "<plan name>"`
3. Create one task per plan step: `todo create "<step>" -c Backlog --project "<plan>" -P N`
4. Add dependencies where ordering matters: `todo dep create task-NNNN task-MMMM`
5. Move tasks to "In Progress" when starting: `todo mv task-NNNN "In Progress"`
6. Mark tasks done when complete: `todo mv task-NNNN Done`
7. Run `todo export` at milestones for a full status snapshot
```

## Data Model

**Hierarchy:** Board → Column → Task (and Board → Project → Task)

Columns are board-scoped and represent kanban workflow stages. No data is ever deleted — use `archived` flags instead. All mutations are recorded in the task history audit trail.

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
