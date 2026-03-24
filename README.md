# sticky-notes

A local todo/kanban app with three interfaces:

- **CLI** (argparse) — task management from the terminal
- **TUI** (Textual) — interactive kanban board with keyboard navigation
- **MCP server** (FastMCP) — Claude interaction via streamable-HTTP

All interfaces share the same database and service layer, backed by **SQLite**.

## Architecture

```
CLI commands ────────┐
TUI event handlers ──┤
                     ├──▶ Service ──▶ Repository ──▶ Connection ──▶ SQLite
MCP tool functions ──┘
```

## Quick Start

```sh
# Install in editable mode
pip install -e .

# Create a board (automatically becomes the active board)
todo board create work

# Add default columns
todo col add "To Do"
todo col add "In Progress"
todo col add "Done"

# Add and manage tasks
todo add "Write README"
todo ls
todo mv task-0001 "In Progress"
todo done task-0001

# Launch the TUI
todo --tui
```

## CLI Usage

Entry point: `todo`

**Active board:** The CLI tracks the active board in `~/.local/share/sticky-notes/active-board`. Override per-command with `--board`/`-b`.

### Task Commands

| Command | Description |
|---------|-------------|
| `todo add <title>` | Add a task to the first column |
| `todo ls` | List tasks on the active board |
| `todo show <task>` | Show task detail with history and dependencies |
| `todo edit <task>` | Edit task fields (`--title`, `--desc`, `--priority`, `--due`, `--project`) |
| `todo mv <task> <column>` | Move task to a column |
| `todo mv <task> <col> --board <board>` | Move task to a different board (copies and archives original) |
| `todo mv <task> --project <project>` | Change task's project within the current board |
| `todo mv <task> <col> --dry-run` | Preview a move without executing (shows dependency warnings) |
| `todo done <task>` | Move task to the last column |
| `todo rm <task>` | Archive a task |
| `todo log <task>` | Show task change history |

### List Filters

`todo ls` supports filtering:

| Flag | Description |
|------|-------------|
| `--all` / `-a` | Include archived tasks |
| `--column` / `-c` | Filter by column name |
| `--project` / `-p` | Filter by project name |
| `--priority` / `-P` | Filter by priority (1-5) |
| `--search` / `-s` | Search by title substring |

### Management Commands

| Command | Description |
|---------|-------------|
| `todo board ...` | `create`, `ls`, `use`, `rename`, `archive` |
| `todo col ...` | `add`, `ls`, `rename`, `archive` |
| `todo project ...` | `create`, `ls`, `show`, `archive` |
| `todo dep ...` | `add`, `rm` |
| `todo export` | Export database to Markdown with Mermaid dependency graphs |

### Cross-Board Moves

Tasks can be moved between boards. The move creates a copy on the target board and archives the original. Dependencies must be removed before moving:

```sh
# Move task to another board
todo mv task-0001 "Backlog" --board ops

# Move with project assignment on the target board
todo mv task-0001 "Backlog" --board ops --project infra

# Preview before moving (checks for blocking dependencies)
todo mv task-0001 "Backlog" --board ops --dry-run
```

## TUI

Launch with `todo --tui` (or `todo --tui --db path/to/db`).

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

## MCP Server

The MCP server exposes the service layer over streamable-HTTP for use by Claude and other MCP clients.

Entry point: `sticky-notes-mcp`

```sh
# Start the server (default: 127.0.0.1:8741)
sticky-notes-mcp

# Custom host/port
sticky-notes-mcp --host 0.0.0.0 --port 9000
```

### Tools

Each tool uses an `action` parameter to dispatch operations, keeping the tool list compact.

| Tool | Actions | Notes |
|------|---------|-------|
| `board` | `create`, `get`, `list`, `update` | `get` accepts `board_id` or `name` |
| `column` | `create`, `list`, `update` | Always scoped to a `board_id` |
| `project` | `create`, `get`, `list`, `update` | `get` returns hydrated `ProjectDetail` |
| `task` | `create`, `get`, `list`, `update`, `move`, `move_to_board` | `move_to_board` copies task to target board and archives original |
| `dependency` | `add`, `remove` | Takes `task_id` + `depends_on_id` |
| `task_history` | `list` | Takes `task_id` |
| `export` | *(none)* | Returns full database as Markdown |

All tools require explicit `board_id` — there is no active board concept in the MCP interface.

Use `clear_fields` on `task` and `project` update actions to set nullable fields to null (e.g. `clear_fields=["due_date", "description"]`).

### Linux Install

The systemd service expects `sticky-notes-mcp` at `~/.local/bin/sticky-notes-mcp`. Install with `--user` to place it there:

```sh
pip install --user .
```

Verify the binary is in place:

```sh
ls ~/.local/bin/sticky-notes-mcp
```

If you use `pip install -e .` (editable/dev mode) instead, the script lands in your active Python environment's `bin/` directory (e.g. `~/.pyenv/versions/3.12.x/bin/`). In that case, update the `ExecStart` path in the service file to match, or create a symlink:

```sh
ln -s "$(which sticky-notes-mcp)" ~/.local/bin/sticky-notes-mcp
```

Then enable the systemd user service:

```sh
cp scripts/sticky-notes-mcp.service ~/.config/systemd/user/
systemctl --user enable --now sticky-notes-mcp
loginctl enable-linger $USER   # allows the service to run without an active login session
```

## Claude Code Integration

The sticky-notes MCP server can be used by Claude Code to persistently track multi-step plans. To set this up:

1. Run the MCP server (see above) and configure it in your Claude Code MCP settings
2. Create a board for Claude to use: `todo board create Claude`
3. Add workflow columns: `todo col add Backlog && todo col add "In Progress" && todo col add Done`
4. Add the following to your global `~/.claude/CLAUDE.md`:

```markdown
## Workflow Tracking with sticky-notes MCP

For multi-step plans (5+ steps), use the sticky-notes MCP server to track progress persistently.
All work lives on the **"Claude" board** which has three columns: Backlog, In Progress, Done.

1. Look up the Claude board: `board(action="get", name="Claude")` — note the `board_id`
2. List columns: `column(action="list", board_id=<id>)` — note column IDs
3. Create a project for the plan: `project(action="create", board_id=<id>, name="<plan name>")`
4. Create one task per plan step, assigning each to the project and the Backlog column
5. Add dependencies between tasks where ordering matters
6. Move tasks to "In Progress" when starting, "Done" when complete
7. Call `export()` at milestones to get a full status snapshot
```

Claude will then automatically use the sticky-notes board to track progress on complex tasks across conversations.

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
- [FastMCP](https://github.com/jlowin/fastmcp) >= 3.1.0 (MCP server)

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
todo --tui --db tmp/test.db
```
