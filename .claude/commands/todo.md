Sticky Notes CLI reference for task/kanban management via bash.

Use `--json` on any command for structured JSON output. All commands use the **active board** by default (override with `-b NAME`). Use `-q`/`--quiet` to suppress stdout on success.

## Quick Start Workflow

```bash
todo board create claude --columns Backlog,"In Progress",Done   # seed columns at creation
todo board use claude                                            # switch to board

todo project create "<plan name>"
todo create "<step>" -c Backlog --project "<plan>" -P N         # -P for priority
todo dep create task-NNNN task-MMMM                             # NNNN blocked by MMMM
todo mv task-NNNN "In Progress"                                 # start work
todo mv task-NNNN Done                                          # complete
todo export                                                     # full status snapshot
```

## Command Reference

### Tasks

```
todo create TITLE -c COLUMN [--desc TEXT] [--project NAME] [-P 1-5] [--due YYYY-MM-DD] [-t TAG]
todo ls [--all] [--archived] [-c COLUMN] [--project NAME] [-P N] [--search TEXT] [--group NAME]
todo show TASK [--by-title]          # TASK: 1 | 0001 | task-0001 | #1
todo edit TASK [--title T] [--desc T] [-P N] [--due YYYY-MM-DD] [--project NAME] [-t TAG] [--untag TAG] [--by-title]
todo mv TASK COLUMN [POSITION]       # within-board move only
todo rm TASK [--by-title]            # soft-delete (sets archived=true)
todo log TASK                        # change history
```

Task identifiers default to numeric formats (`1`, `task-0001`, `#1`). Pass `--by-title` on any command to resolve by title string instead.

### Cross-board Transfer

```
todo transfer TASK --board TARGET_BOARD --column COLUMN [--project NAME] [--dry-run] [--by-title]
```

Archives the source task and creates a copy on the target board. Use `--dry-run` to preview without making changes.

### Boards

```
todo board create NAME [--columns col1,col2,...]   # creates and sets as active
todo board ls [--all]
todo board use NAME
todo board rename [OLD_NAME] NEW_NAME              # OLD_NAME optional; defaults to active board
todo board rm [NAME]                               # archives board; NAME optional
```

### Columns

```
todo col create NAME [--pos N]
todo col ls
todo col rename OLD NEW
todo col rm NAME [--reassign-to OTHER_COL | --force]  # --force archives with tasks
```

### Projects

```
todo project create NAME [--desc TEXT]
todo project ls
todo project show NAME
todo project rm NAME
```

### Dependencies

```
todo dep create TASK DEPENDS_ON    # TASK is blocked by DEPENDS_ON
todo dep rm TASK DEPENDS_ON        # hard-deletes the dependency link
```

### Groups

```
todo group create TITLE -p PROJECT [--parent TITLE]
todo group ls [--project NAME] [--all] [--tree]
todo group show TITLE [--project NAME]
todo group rename TITLE NEW_TITLE [--project NAME]
todo group rm TITLE [--project NAME]
todo group mv TITLE --parent PARENT_TITLE [--project NAME]   # --parent "" to promote to root
todo group assign TASK GROUP_TITLE [-p PROJECT] [--by-title]
todo group unassign TASK [--by-title]
```

### Tags

```
todo tag create NAME
todo tag ls [--all]
todo tag rm NAME [--unassign]    # archives tag; --unassign also removes from active tasks
```

### Export & TUI

```
todo export [-o FILE] [--json]
todo tui [--db PATH]
```

---

## JSON Output (`--json`)

All commands return the same envelope:

```json
{"ok": true,  "data": <payload>}
{"ok": false, "error": "message", "code": "slug"}
```

Successes write to **stdout**. Errors write to **stderr** (in both text and JSON modes).

### Error codes

| code | meaning |
|---|---|
| `not_found` | entity doesn't exist |
| `validation` | bad argument value |
| `no_change` | no-op (not an error, won't appear) |
| `conflict` | duplicate name or integrity violation |
| `missing_active_board` | no active board set |
| `db_error` | SQLite error (exits 2) |

### `data` shapes by command

| Command | `data` shape |
|---|---|
| `create`, `edit`, `rm`, `mv` | full Task object |
| `board create/rename/rm` | full Board object |
| `col create/rename/rm` | full Column object |
| `project create/rm` | full Project object |
| `tag create/rm` | full Tag object |
| `dep create/rm` | `{"task_id": N, "depends_on_id": N}` |
| `group assign` | `{"task": {...}, "group_id": N}` |
| `group unassign` | full Task object |
| `transfer` (live) | `{"task": {...}, "source_task_id": N}` |
| `transfer --dry-run` | `{"can_move": bool, "dependency_ids": [...], "blocking_reason": str\|null, "is_archived": bool, ...}` |
| `ls` | `{"board": {...}, "columns": [{"column": {...}, "tasks": [...]}]}` |
| `board ls` | array of Board objects with `"active": bool` field |
| `col ls` | array of Column objects |
| `project ls` | array of Project objects |
| `tag ls` | array of Tag objects |
| `group ls` | array of GroupRef objects |
| `show` | full TaskDetail (with `column`, `project`, `group`, `tags`, `blocked_by`, `blocks`, `history`) |
| `project show` | ProjectDetail with `tasks` array |
| `group show` | GroupDetail with `tasks` and `children` arrays |
| `log` | array of TaskHistory objects |
| `export` | `{"markdown": "..."}` or `{"output_path": "...", "bytes": N}` when `-o FILE` |

### Examples

```bash
# create a task
todo --json create "Fix login bug" -c backlog -P 3
# → {"ok": true, "data": {"id": 42, "title": "Fix login bug", "priority": 3, ...}}

# show with full detail
todo --json show 42
# → {"ok": true, "data": {"id": 42, "column": {"name": "backlog"}, "tags": [...], ...}}

# list board
todo --json ls
# → {"ok": true, "data": {"board": {"name": "dev"}, "columns": [...]}}

# cross-board transfer dry-run
todo --json transfer 42 --board ops --column inbox --dry-run
# → {"ok": true, "data": {"can_move": true, "dependency_ids": [], ...}}

# error
todo --json show 9999
# stderr: {"ok": false, "error": "task 9999 not found", "code": "not_found"}
```

---

## Conventions

- Task IDs: `task-NNNN` (zero-padded integer). Pass as `1`, `0001`, `task-0001`, or `#1`.
- Priority: 1 (lowest) to 5 (highest), default 1. Short flag `-P N`.
- Dates: `YYYY-MM-DD` on input and output.
- `rm`/`archive` sets `archived=true` — no data is permanently deleted except `dep rm`.
- `edit` with no field flags is a no-op (returns unchanged task, exit 0).
- Active board: `~/.local/share/sticky-notes/active-board`
- Database: `~/.local/share/sticky-notes/sticky-notes.db`
- JSON writes to stdout on success, stderr on error (both text and JSON mode).
