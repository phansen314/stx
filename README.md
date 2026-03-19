# sticky-notes

A local todo/kanban app with three interfaces:

- **CLI** (argparse) — primary interface today
- **TUI** (Textual) — human interaction *(not yet built)*
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
```

## CLI Usage

Entry point: `todo`

**Active board:** The CLI tracks the active board in `~/.local/share/sticky-notes/active-board`. Override per-command with `--board`/`-b`.

| Command | Description |
|---------|-------------|
| `todo add <title>` | Add a task to the first column |
| `todo ls` | List tasks on the active board |
| `todo show <task>` | Show task detail |
| `todo edit <task>` | Edit task fields |
| `todo mv <task> <column>` | Move task to a column |
| `todo done <task>` | Move task to the last column |
| `todo rm <task>` | Archive a task |
| `todo log <task>` | Show task change history |
| `todo board ...` | `create`, `ls`, `use`, `rename`, `archive` |
| `todo col ...` | `add`, `ls`, `rename`, `archive` |
| `todo project ...` | `create`, `ls`, `show`, `archive` |
| `todo dep ...` | `add`, `rm` |
| `todo export` | Export database to Markdown |

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
| `task` | `create`, `get`, `list`, `update`, `move` | `get` returns `TaskDetail`, `list` returns `TaskRef[]` |
| `dependency` | `add`, `remove` | Takes `task_id` + `depends_on_id` |
| `task_history` | `list` | Takes `task_id` |
| `export` | *(none)* | Returns full database as Markdown |

All tools require explicit `board_id` — there is no active board concept in the MCP interface.

### Linux install

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

### macOS install

The macOS LaunchAgent keeps the MCP server running automatically. Install `sticky-notes-mcp` first:

```sh
pip install --user .
```

Verify the binary is on PATH:

```sh
command -v sticky-notes-mcp
```

Then run the install script:

```sh
./macosx/install.sh
```

This installs a LaunchAgent that starts the server at login and restarts it on failure. Logs go to `~/Library/Logs/sticky-notes-mcp/`.

To uninstall:

```sh
./macosx/uninstall.sh
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

Columns are board-scoped and represent kanban workflow stages. No data is ever deleted — use `archived` flags instead.

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

Fresh in-memory DB per test — no cross-test pollution.
