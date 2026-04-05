from __future__ import annotations

import pytest
from pathlib import Path

from sticky_notes.active_board import (
    active_board_path,
    get_active_board_id,
    set_active_board_id,
)
from sticky_notes.cli import main
from sticky_notes.formatting import (
    format_priority,
    format_task_num,
    format_timestamp,
    parse_date,
    parse_task_num,
)


# ---- Fixtures ----


@pytest.fixture
def cli(db_path: Path, capsys: pytest.CaptureFixture[str]):
    def run(*args: str, expect_exit: int = 0) -> tuple[str, str]:
        argv = ["--db", str(db_path), *args]
        try:
            main(argv)
        except SystemExit as exc:
            assert exc.code == expect_exit, (
                f"expected exit {expect_exit}, got {exc.code}\n"
                f"stderr: {capsys.readouterr().err}"
            )
        captured = capsys.readouterr()
        return captured.out, captured.err

    return run


# ---- Parse helpers ----


class TestParseTaskNum:
    def test_plain_int(self):
        assert parse_task_num("1") == 1

    def test_padded(self):
        assert parse_task_num("0001") == 1

    def test_task_prefix(self):
        assert parse_task_num("task-0001") == 1

    def test_hash_prefix(self):
        assert parse_task_num("#42") == 42

    def test_invalid(self):
        with pytest.raises(ValueError, match="invalid task number"):
            parse_task_num("abc")

    def test_zero(self):
        with pytest.raises(ValueError, match="invalid task number"):
            parse_task_num("0")


class TestParseDate:
    def test_valid(self):
        epoch = parse_date("2026-03-14")
        assert epoch == 1773446400

    def test_invalid(self):
        with pytest.raises(ValueError, match="invalid date"):
            parse_date("not-a-date")


class TestFormatHelpers:
    def test_format_task_num(self):
        assert format_task_num(1) == "task-0001"
        assert format_task_num(9999) == "task-9999"

    def test_format_timestamp(self):
        assert format_timestamp(1773446400) == "2026-03-14"

    def test_format_priority(self):
        assert format_priority(1) == "[P1]"
        assert format_priority(3) == "[P3]"


# ---- Active board helpers ----


class TestActiveBoard:
    def test_path(self, db_path: Path):
        assert active_board_path(db_path) == db_path.parent / "active-board"

    def test_get_none(self, db_path: Path):
        assert get_active_board_id(db_path) is None

    def test_set_and_get(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        set_active_board_id(db_path, 42)
        assert get_active_board_id(db_path) == 42


# ---- Board commands ----


class TestBoardCommands:
    def test_create(self, cli):
        out, _ = cli("board", "create", "dev")
        assert "created board 'dev' (active)" in out

    def test_create_auto_activates(self, cli, db_path):
        cli("board", "create", "dev")
        assert get_active_board_id(db_path) is not None

    def test_ls(self, cli):
        cli("board", "create", "dev")
        cli("board", "create", "ops")
        out, _ = cli("board", "ls")
        assert "dev" in out
        assert "ops" in out

    def test_ls_shows_active_marker(self, cli):
        cli("board", "create", "dev")
        out, _ = cli("board", "ls")
        assert "dev *" in out

    def test_ls_empty(self, cli):
        out, _ = cli("board", "ls")
        assert "no boards" in out

    def test_use(self, cli, db_path):
        cli("board", "create", "dev")
        cli("board", "create", "ops")
        cli("board", "use", "dev")
        out, _ = cli("board", "ls")
        assert "dev *" in out

    def test_rename(self, cli):
        cli("board", "create", "dev")
        out, _ = cli("board", "rename", "staging")
        assert "renamed board 'dev' -> 'staging'" in out

    def test_archive(self, cli):
        cli("board", "create", "dev")
        out, _ = cli("board", "rm")
        assert "archived board" in out

    def test_archive_active_board_clears_pointer(self, cli, db_path):
        cli("board", "create", "dev")
        assert get_active_board_id(db_path) is not None
        cli("board", "rm")
        assert get_active_board_id(db_path) is None

    def test_archive_non_active_board_leaves_pointer(self, cli, db_path):
        cli("board", "create", "dev")
        cli("board", "create", "ops")
        cli("board", "use", "dev")
        # ops is not active — archiving it must not clear the pointer
        cli("-b", "ops", "board", "rm")
        assert get_active_board_id(db_path) is not None

    def test_use_nonexistent(self, cli):
        _, err = cli("board", "use", "nope", expect_exit=1)
        assert "error:" in err


# ---- Column commands ----


class TestColumnCommands:
    def test_add(self, cli):
        cli("board", "create", "dev")
        out, _ = cli("col", "create", "backlog")
        assert "created column 'backlog'" in out

    def test_add_with_position(self, cli):
        cli("board", "create", "dev")
        cli("col", "create", "backlog", "--pos", "0")
        cli("col", "create", "done", "--pos", "2")
        cli("col", "create", "in progress", "--pos", "1")
        out, _ = cli("col", "ls")
        lines = out.strip().split("\n")
        assert "backlog" in lines[0]
        assert "in progress" in lines[1]
        assert "done" in lines[2]

    def test_ls(self, cli):
        cli("board", "create", "dev")
        cli("col", "create", "todo")
        cli("col", "create", "done", "--pos", "1")
        out, _ = cli("col", "ls")
        assert "todo" in out
        assert "done" in out

    def test_ls_empty(self, cli):
        cli("board", "create", "dev")
        out, _ = cli("col", "ls")
        assert "no columns" in out  # _empty("column") = "no columns"

    def test_rename(self, cli):
        cli("board", "create", "dev")
        cli("col", "create", "todo")
        out, _ = cli("col", "rename", "todo", "backlog")
        assert "renamed column 'todo' -> 'backlog'" in out

    def test_archive(self, cli):
        cli("board", "create", "dev")
        cli("col", "create", "todo")
        out, _ = cli("col", "rm", "todo")
        assert "archived column 'todo'" in out


# ---- Task shortcuts ----


class TestTaskCommands:
    @pytest.fixture(autouse=True)
    def _setup(self, cli):
        cli("board", "create", "dev")
        cli("col", "create", "todo", "--pos", "0")
        cli("col", "create", "in progress", "--pos", "1")
        cli("col", "create", "done", "--pos", "2")

    def test_add_default_column(self, cli):
        out, _ = cli("create", "Fix login bug", "-c", "todo")
        assert "created task-0001" in out

    def test_add_explicit_column(self, cli):
        out, _ = cli("create", "My task", "-c", "in progress")
        assert "created task-0001" in out

    def test_add_with_project(self, cli):
        cli("project", "create", "backend")
        out, _ = cli("create", "Fix bug", "-p", "backend", "-c", "todo")
        assert "created task-0001" in out

    def test_add_with_priority_and_due(self, cli):
        out, _ = cli("create", "Important", "--priority", "3", "--due", "2026-04-01", "-c", "todo")
        assert "created task-0001" in out

    def test_add_with_desc(self, cli):
        out, _ = cli("create", "Fix it", "-d", "Full description here", "-c", "todo")
        assert "created task-0001" in out

    def test_ls_grouped_by_column(self, cli):
        cli("create", "Task A", "-c", "todo")
        cli("create", "Task B", "-c", "in progress")
        out, _ = cli("ls")
        assert "== todo ==" in out
        assert "Task A" in out
        assert "== in progress ==" in out
        assert "Task B" in out
        assert "== done ==" in out
        assert "(empty)" in out

    def test_ls_shows_project(self, cli):
        cli("project", "create", "backend")
        cli("create", "Fix bug", "-p", "backend", "-c", "todo")
        out, _ = cli("ls")
        assert "@backend" in out

    def test_ls_shows_priority(self, cli):
        cli("create", "Fix bug", "--priority", "3", "-c", "todo")
        out, _ = cli("ls")
        assert "[P3]" in out

    def test_show(self, cli):
        cli("create", "Fix login bug", "--priority", "2", "--due", "2026-04-01", "-c", "todo")
        out, _ = cli("show", "1")
        assert "task-0001" in out
        assert "Fix login bug" in out
        assert "Priority:    2" in out
        assert "Due:         2026-04-01" in out
        assert "Column:      todo" in out

    def test_show_with_project(self, cli):
        cli("project", "create", "backend")
        cli("create", "Fix bug", "-p", "backend", "-c", "todo")
        out, _ = cli("show", "1")
        assert "Project:     backend" in out

    def test_show_with_deps(self, cli):
        cli("create", "Task A", "-c", "todo")
        cli("create", "Task B", "-c", "todo")
        cli("dep", "create", "2", "1")
        out, _ = cli("show", "2")
        assert "Blocked by:  task-0001" in out
        # Also check the "Blocks" line from the other side
        out2, _ = cli("show", "1")
        assert "Blocks:      task-0002" in out2

    def test_show_with_description(self, cli):
        cli("create", "Fix bug", "-d", "Detailed description", "-c", "todo")
        out, _ = cli("show", "1")
        assert "Description:" in out
        assert "Detailed description" in out

    def test_edit_title(self, cli):
        cli("create", "Old title", "-c", "todo")
        out, _ = cli("edit", "1", "--title", "New title")
        assert "updated task-0001" in out
        show_out, _ = cli("show", "1")
        assert "New title" in show_out

    def test_edit_priority(self, cli):
        cli("create", "Task", "-c", "todo")
        cli("edit", "1", "--priority", "5")
        out, _ = cli("show", "1")
        assert "Priority:    5" in out

    def test_edit_desc(self, cli):
        cli("create", "Task", "-c", "todo")
        cli("edit", "1", "-d", "new desc")
        out, _ = cli("show", "1")
        assert "new desc" in out

    def test_edit_due(self, cli):
        cli("create", "Task", "-c", "todo")
        cli("edit", "1", "--due", "2026-06-01")
        out, _ = cli("show", "1")
        assert "Due:         2026-06-01" in out

    def test_edit_project(self, cli):
        cli("project", "create", "backend")
        cli("create", "Task", "-c", "todo")
        cli("edit", "1", "-p", "backend")
        out, _ = cli("show", "1")
        assert "Project:     backend" in out

    def test_edit_nothing(self, cli):
        cli("create", "Task", "-c", "todo")
        out, _ = cli("edit", "1")  # no-op: returns task unchanged, exit 0
        assert "updated task-0001" in out

    def test_mv(self, cli):
        cli("create", "Task A", "-c", "todo")
        out, _ = cli("mv", "1", "in progress")
        assert "moved task-0001 -> in progress" in out

    def test_mv_case_insensitive(self, cli):
        cli("create", "Task A", "-c", "todo")
        out, _ = cli("mv", "1", "In Progress")
        assert "moved task-0001 -> in progress" in out

    def test_rm(self, cli):
        cli("create", "Task A", "-c", "todo")
        out, _ = cli("rm", "1")
        assert "archived task-0001" in out

    def test_rm_hides_from_ls(self, cli):
        cli("create", "Task A", "-c", "todo")
        cli("rm", "1")
        out, _ = cli("ls")
        assert "Task A" not in out

    def test_log(self, cli):
        cli("create", "Task A", "-c", "todo")
        cli("edit", "1", "--title", "Task B")
        out, _ = cli("log", "1")
        assert "title:" in out
        assert "Task A" in out
        assert "Task B" in out
        assert "(cli)" in out

    def test_log_empty(self, cli):
        cli("create", "Task A", "-c", "todo")
        out, _ = cli("log", "1")
        assert "no history" in out

    def test_show_nonexistent(self, cli):
        _, err = cli("show", "999", expect_exit=1)
        assert "error:" in err

    def test_task_num_formats(self, cli):
        cli("create", "Task A", "-c", "todo")
        out1, _ = cli("show", "task-0001")
        out2, _ = cli("show", "#1")
        out3, _ = cli("show", "0001")
        assert "Task A" in out1
        assert "Task A" in out2
        assert "Task A" in out3

    def test_show_by_title(self, cli):
        cli("create", "Fix login bug", "-c", "todo")
        out, _ = cli("show", "Fix login bug", "--by-title")
        assert "task-0001" in out
        assert "Fix login bug" in out

    def test_show_by_title_not_found(self, cli):
        _, err = cli("show", "nonexistent title", "--by-title", expect_exit=1)
        assert "error:" in err

    def test_dep_create_by_title(self, cli):
        cli("create", "Task A", "-c", "todo")
        cli("create", "Task B", "-c", "todo")
        out, _ = cli("dep", "create", "Task B", "Task A", "--by-title")
        assert "task-0002 now blocked by task-0001" in out


# ---- Project commands ----


class TestProjectCommands:
    @pytest.fixture(autouse=True)
    def _setup(self, cli):
        cli("board", "create", "dev")

    def test_create(self, cli):
        out, _ = cli("project", "create", "backend")
        assert "created project 'backend'" in out

    def test_create_with_desc(self, cli):
        out, _ = cli("project", "create", "backend", "-d", "Backend services")
        assert "created project 'backend'" in out

    def test_ls(self, cli):
        cli("project", "create", "backend")
        cli("project", "create", "frontend")
        out, _ = cli("project", "ls")
        assert "backend" in out
        assert "frontend" in out

    def test_ls_empty(self, cli):
        out, _ = cli("project", "ls")
        assert "no projects" in out

    def test_show(self, cli):
        cli("col", "create", "todo")
        cli("project", "create", "backend", "-d", "API layer")
        cli("create", "Fix bug", "-p", "backend", "-c", "todo")
        out, _ = cli("project", "show", "backend")
        assert "backend" in out
        assert "API layer" in out
        assert "Tasks: 1" in out
        assert "Fix bug" in out

    def test_archive(self, cli):
        cli("project", "create", "backend")
        out, _ = cli("project", "rm", "backend")
        assert "archived project 'backend'" in out


# ---- Dependency commands ----


class TestDependencyCommands:
    @pytest.fixture(autouse=True)
    def _setup(self, cli):
        cli("board", "create", "dev")
        cli("col", "create", "todo")

    def test_add(self, cli):
        cli("create", "Task A", "-c", "todo")
        cli("create", "Task B", "-c", "todo")
        out, _ = cli("dep", "create", "2", "1")
        assert "task-0002 now blocked by task-0001" in out

    def test_rm(self, cli):
        cli("create", "Task A", "-c", "todo")
        cli("create", "Task B", "-c", "todo")
        cli("dep", "create", "2", "1")
        out, _ = cli("dep", "rm", "2", "1")
        assert "removed dependency" in out


# ---- Error handling ----


class TestErrorHandling:
    def test_no_active_board(self, cli):
        _, err = cli("ls", expect_exit=1)
        assert "no active board" in err

    def test_not_found(self, cli):
        cli("board", "create", "dev")
        _, err = cli("show", "999", expect_exit=1)
        assert "error:" in err

    def test_duplicate_board_name(self, cli):
        cli("board", "create", "dev")
        _, err = cli("board", "create", "dev", expect_exit=1)
        assert "error:" in err

    def test_invalid_task_num(self, cli):
        cli("board", "create", "dev")
        _, err = cli("show", "abc", expect_exit=1)
        assert "error:" in err

    def test_column_not_found(self, cli):
        cli("board", "create", "dev")
        cli("col", "create", "todo")
        _, err = cli("create", "Task", "-c", "nonexistent", expect_exit=1)
        assert "not found" in err

    def test_project_not_found(self, cli):
        cli("board", "create", "dev")
        cli("col", "create", "todo")
        _, err = cli("create", "Task", "-c", "todo", "-p", "nonexistent", expect_exit=1)
        assert "not found" in err

    def test_archive_column_with_active_tasks_blocked(self, cli):
        cli("board", "create", "dev")
        cli("col", "create", "todo")
        cli("create", "Task", "-c", "todo")
        _, err = cli("col", "rm", "todo", expect_exit=1)
        assert "active task" in err


# ---- Board flag override ----


class TestBoardFlag:
    def test_board_flag(self, cli):
        cli("board", "create", "dev")
        cli("board", "create", "ops")
        cli("-b", "dev", "col", "create", "todo")
        out, _ = cli("-b", "dev", "col", "ls")
        assert "todo" in out

    def test_board_flag_overrides_active(self, cli):
        cli("board", "create", "dev")
        cli("board", "create", "ops")
        # ops is now active (last created)
        cli("-b", "dev", "col", "create", "backlog")
        out, _ = cli("-b", "dev", "col", "ls")
        assert "backlog" in out
        # ops has no columns
        out2, _ = cli("col", "ls")
        assert "no columns" in out2


# ---- Help output ----


class TestLsFilters:
    def _setup_board(self, cli):
        cli("board", "create", "work")
        cli("col", "create", "backlog")
        cli("col", "create", "doing")
        cli("project", "create", "alpha")

    def test_filter_by_column(self, cli):
        self._setup_board(cli)
        cli("create", "task1", "-c", "backlog")
        cli("create", "task2", "-c", "doing")
        out, _ = cli("ls", "-c", "backlog")
        assert "task1" in out
        assert "task2" not in out or "task2" not in out.split("== backlog ==")[0]

    def test_filter_by_project(self, cli):
        self._setup_board(cli)
        cli("create", "task1", "-p", "alpha", "-c", "backlog")
        cli("create", "task2", "-c", "backlog")
        out, _ = cli("ls", "-p", "alpha")
        assert "task1" in out
        # task2 not in any non-empty column section
        lines = [l for l in out.splitlines() if "task2" in l]
        assert len(lines) == 0

    def test_filter_by_priority(self, cli):
        self._setup_board(cli)
        cli("create", "low", "--priority", "1", "-c", "backlog")
        cli("create", "high", "--priority", "3", "-c", "backlog")
        out, _ = cli("ls", "-P", "3")
        assert "high" in out
        lines = [l for l in out.splitlines() if "low" in l]
        assert len(lines) == 0

    def test_filter_by_search(self, cli):
        self._setup_board(cli)
        cli("create", "Fix login bug", "-c", "backlog")
        cli("create", "Add search feature", "-c", "backlog")
        out, _ = cli("ls", "-s", "login")
        assert "Fix login bug" in out
        lines = [l for l in out.splitlines() if "search feature" in l]
        assert len(lines) == 0

    def test_combined_filters(self, cli):
        self._setup_board(cli)
        cli("create", "task1", "-c", "backlog", "--priority", "3")
        cli("create", "task2", "-c", "backlog", "--priority", "1")
        cli("create", "task3", "-c", "doing", "--priority", "3")
        out, _ = cli("ls", "-c", "backlog", "-P", "3")
        assert "task1" in out
        lines = [l for l in out.splitlines() if l.strip().startswith("task-")]
        assert len(lines) == 1

    def test_invalid_column_name(self, cli):
        self._setup_board(cli)
        _, err = cli("ls", "-c", "nonexistent", expect_exit=1)
        assert "not found" in err

    def test_invalid_project_name(self, cli):
        self._setup_board(cli)
        _, err = cli("ls", "-p", "nonexistent", expect_exit=1)
        assert "not found" in err


class TestMvBoard:
    @pytest.fixture(autouse=True)
    def _setup(self, cli):
        cli("board", "create", "dev")
        cli("col", "create", "todo", "--pos", "0")
        cli("col", "create", "done", "--pos", "1")

    def test_transfer_to_board(self, cli):
        cli("board", "create", "ops")
        cli("board", "use", "ops")
        cli("col", "create", "backlog")
        cli("board", "use", "dev")
        cli("create", "Task A", "-c", "todo")
        out, _ = cli("transfer", "1", "--board", "ops", "--column", "backlog")
        assert "board 'ops'" in out
        assert "column 'backlog'" in out

    def test_transfer_to_board_with_project(self, cli):
        cli("board", "create", "ops")
        cli("board", "use", "ops")
        cli("col", "create", "backlog")
        cli("project", "create", "infra")
        cli("board", "use", "dev")
        cli("create", "Task A", "-c", "todo")
        out, _ = cli("transfer", "1", "--board", "ops", "--column", "backlog", "-p", "infra")
        assert "board 'ops'" in out

    def test_transfer_no_column_fails(self, cli):
        cli("board", "create", "ops")
        cli("board", "use", "dev")
        cli("create", "Task A", "-c", "todo")
        _, err = cli("transfer", "1", "--board", "ops", expect_exit=2)
        assert "--column" in err or "required" in err

    def test_mv_project_only_use_edit(self, cli):
        cli("project", "create", "backend")
        cli("create", "Task A", "-c", "todo")
        out, _ = cli("edit", "1", "-p", "backend")
        assert "updated" in out

    def test_mv_no_column_fails(self, cli):
        cli("create", "Task A", "-c", "todo")
        _, err = cli("mv", "1", expect_exit=2)
        assert "error" in err.lower() or "usage" in err.lower()

    def test_transfer_dry_run(self, cli):
        cli("board", "create", "ops")
        cli("board", "use", "ops")
        cli("col", "create", "backlog")
        cli("board", "use", "dev")
        cli("create", "Task A", "-c", "todo")
        out, _ = cli("transfer", "1", "--board", "ops", "--column", "backlog", "--dry-run")
        assert "dry-run" in out
        assert "transfer OK" in out

    def test_transfer_dry_run_with_deps(self, cli):
        cli("board", "create", "ops")
        cli("board", "use", "ops")
        cli("col", "create", "backlog")
        cli("board", "use", "dev")
        cli("create", "Task A", "-c", "todo")
        cli("create", "Task B", "-c", "todo")
        cli("dep", "create", "2", "1")
        out, _ = cli("transfer", "1", "--board", "ops", "--column", "backlog", "--dry-run")
        assert "dependencies" in out
        assert "FAIL" in out


class TestGroupCLI:
    """Fixture `cli` provides a helper that always passes --db to a temp DB.
    Each test creates its own board/project/column setup."""

    @pytest.fixture(autouse=True)
    def _setup(self, cli):
        self.cli = cli
        cli("board", "create", "dev")
        cli("col", "create", "todo")
        cli("project", "create", "sprint1")

    def test_create_group(self):
        out, _ = self.cli("group", "create", "Frontend", "--project", "sprint1")
        assert "created group 'Frontend'" in out
        assert "group-0001" in out

    def test_create_with_parent(self):
        self.cli("group", "create", "Frontend", "--project", "sprint1")
        out, _ = self.cli("group", "create", "Components", "--project", "sprint1", "--parent", "Frontend")
        assert "created group 'Components'" in out

    def test_create_requires_project(self):
        _, err = self.cli("group", "create", "Orphan", expect_exit=2)
        assert "--project" in err and "required" in err

    def test_list_groups(self):
        self.cli("group", "create", "Frontend", "--project", "sprint1")
        self.cli("group", "create", "Backend", "--project", "sprint1")
        out, _ = self.cli("group", "ls", "--project", "sprint1")
        assert "Frontend" in out
        assert "Backend" in out

    def test_list_groups_empty(self):
        out, _ = self.cli("group", "ls", "--project", "sprint1")
        assert "no groups" in out

    def test_list_groups_tree(self):
        self.cli("group", "create", "Frontend", "--project", "sprint1")
        self.cli("group", "create", "Components", "--project", "sprint1", "--parent", "Frontend")
        self.cli("create", "Fix bug", "--project", "sprint1", "-c", "todo")
        self.cli("group", "assign", "task-0001", "Frontend", "--project", "sprint1")
        out, _ = self.cli("group", "ls", "--project", "sprint1", "--tree")
        assert "Frontend" in out
        assert "Components" in out
        assert "task-0001" in out

    def test_show_group(self):
        self.cli("group", "create", "Frontend", "--project", "sprint1")
        self.cli("create", "Fix bug", "--project", "sprint1", "-c", "todo")
        self.cli("group", "assign", "task-0001", "Frontend", "--project", "sprint1")
        out, _ = self.cli("group", "show", "Frontend", "--project", "sprint1")
        assert "Group: Frontend" in out
        assert "group-0001" in out
        assert "sprint1" in out
        assert "task-0001" in out

    def test_show_group_not_found(self):
        _, err = self.cli("group", "show", "nope", "--project", "sprint1", expect_exit=1)
        assert "not found" in err

    def test_rename_group(self):
        self.cli("group", "create", "Frontend", "--project", "sprint1")
        out, _ = self.cli("group", "rename", "Frontend", "UI", "--project", "sprint1")
        assert "renamed" in out
        assert "'UI'" in out

    def test_archive_group(self):
        self.cli("group", "create", "Frontend", "--project", "sprint1")
        out, _ = self.cli("group", "rm", "Frontend", "--project", "sprint1")
        assert "archived group 'Frontend'" in out

    def test_archive_orphans_tasks(self):
        self.cli("group", "create", "Frontend", "--project", "sprint1")
        self.cli("create", "Fix bug", "--project", "sprint1", "-c", "todo")
        self.cli("group", "assign", "task-0001", "Frontend", "--project", "sprint1")
        self.cli("group", "rm", "Frontend", "--project", "sprint1")
        # Task should still exist but not in any group
        out, _ = self.cli("show", "task-0001")
        assert "Group:" not in out

    def test_mv_reparent(self):
        self.cli("group", "create", "Frontend", "--project", "sprint1")
        self.cli("group", "create", "Backend", "--project", "sprint1")
        out, _ = self.cli("group", "mv", "Backend", "--parent", "Frontend", "--project", "sprint1")
        assert "moved" in out
        assert "'Frontend'" in out

    def test_mv_promote_to_top(self):
        self.cli("group", "create", "Frontend", "--project", "sprint1")
        self.cli("group", "create", "Child", "--project", "sprint1", "--parent", "Frontend")
        out, _ = self.cli("group", "mv", "Child", "--parent", "", "--project", "sprint1")
        assert "promoted" in out

    def test_assign_task(self):
        self.cli("group", "create", "Frontend", "--project", "sprint1")
        self.cli("create", "Fix bug", "--project", "sprint1", "-c", "todo")
        out, _ = self.cli("group", "assign", "task-0001", "Frontend", "--project", "sprint1")
        assert "assigned task-0001 to group 'Frontend'" in out

    def test_assign_auto_sets_project(self):
        self.cli("group", "create", "Frontend", "--project", "sprint1")
        self.cli("create", "No project task", "-c", "todo")
        self.cli("group", "assign", "task-0001", "Frontend", "--project", "sprint1")
        out, _ = self.cli("show", "task-0001")
        assert "sprint1" in out

    def test_assign_cross_project_raises(self):
        self.cli("project", "create", "sprint2")
        self.cli("group", "create", "Frontend", "--project", "sprint1")
        self.cli("create", "Task", "--project", "sprint2", "-c", "todo")
        _, err = self.cli("group", "assign", "task-0001", "Frontend", "--project", "sprint1", expect_exit=1)
        assert "project" in err

    def test_unassign_task(self):
        self.cli("group", "create", "Frontend", "--project", "sprint1")
        self.cli("create", "Fix bug", "--project", "sprint1", "-c", "todo")
        self.cli("group", "assign", "task-0001", "Frontend", "--project", "sprint1")
        out, _ = self.cli("group", "unassign", "task-0001")
        assert "unassigned" in out

    def test_show_displays_group(self):
        self.cli("group", "create", "Frontend", "--project", "sprint1")
        self.cli("create", "Fix bug", "--project", "sprint1", "-c", "todo")
        self.cli("group", "assign", "task-0001", "Frontend", "--project", "sprint1")
        out, _ = self.cli("show", "task-0001")
        assert "Group:" in out
        assert "Frontend" in out

    def test_ls_group_filter(self):
        self.cli("group", "create", "Frontend", "--project", "sprint1")
        self.cli("create", "Grouped", "--project", "sprint1", "-c", "todo")
        self.cli("create", "Ungrouped", "--project", "sprint1", "-c", "todo")
        self.cli("group", "assign", "task-0001", "Frontend", "--project", "sprint1")
        out, _ = self.cli("ls", "--group", "Frontend")
        assert "Grouped" in out
        assert "Ungrouped" not in out

    def test_ambiguous_group_requires_project(self):
        self.cli("project", "create", "sprint2")
        self.cli("group", "create", "Shared", "--project", "sprint1")
        self.cli("group", "create", "Shared", "--project", "sprint2")
        _, err = self.cli("group", "show", "Shared", expect_exit=1)
        assert "ambiguous" in err

    def test_cycle_detection(self):
        self.cli("group", "create", "A", "--project", "sprint1")
        self.cli("group", "create", "B", "--project", "sprint1", "--parent", "A")
        _, err = self.cli("group", "mv", "A", "--parent", "B", "--project", "sprint1", expect_exit=1)
        assert "cycle" in err


# ---- Tag ----


class TestTagCommands:
    @pytest.fixture(autouse=True)
    def _setup(self, cli):
        cli("board", "create", "dev")
        cli("col", "create", "todo", "--pos", "0")
        cli("col", "create", "done", "--pos", "1")

    # -- Tag subcommands --

    def test_tag_create(self, cli):
        out, _ = cli("tag", "create", "bug")
        assert "created tag 'bug'" in out

    def test_tag_ls(self, cli):
        cli("tag", "create", "bug")
        cli("tag", "create", "feature")
        out, _ = cli("tag", "ls")
        assert "bug" in out
        assert "feature" in out

    def test_tag_ls_empty(self, cli):
        out, _ = cli("tag", "ls")
        assert "no tags" in out

    def test_tag_rm(self, cli):
        cli("tag", "create", "bug")
        out, _ = cli("tag", "rm", "bug")
        assert "archived tag 'bug'" in out

    def test_tag_rm_not_found(self, cli):
        _, err = cli("tag", "rm", "nonexistent", expect_exit=1)
        assert "not found" in err

    def test_tag_ls_all_shows_archived(self, cli):
        cli("tag", "create", "bug")
        cli("tag", "create", "old")
        cli("tag", "rm", "old")
        out, _ = cli("tag", "ls")
        assert "bug" in out
        assert "old" not in out
        out, _ = cli("tag", "ls", "--all")
        assert "bug" in out
        assert "old" in out
        assert "(archived)" in out

    # -- Tags on add --

    def test_add_with_tag(self, cli):
        cli("create", "Fix bug", "--tag", "bug", "-c", "todo")
        out, _ = cli("show", "1")
        assert "bug" in out

    def test_add_with_multiple_tags(self, cli):
        cli("create", "Fix bug", "-t", "bug", "-t", "urgent", "-c", "todo")
        out, _ = cli("show", "1")
        assert "bug" in out
        assert "urgent" in out

    def test_add_tag_auto_creates(self, cli):
        cli("create", "Fix", "-t", "new-tag", "-c", "todo")
        out, _ = cli("tag", "ls")
        assert "new-tag" in out

    # -- Tags on edit --

    def test_edit_add_tag(self, cli):
        cli("create", "Task", "-c", "todo")
        cli("edit", "1", "--tag", "bug")
        out, _ = cli("show", "1")
        assert "bug" in out

    def test_edit_untag(self, cli):
        cli("create", "Task", "-t", "bug", "-c", "todo")
        cli("edit", "1", "--untag", "bug")
        out, _ = cli("show", "1")
        assert "Tags:" not in out

    def test_edit_tag_only_no_field_changes(self, cli):
        cli("create", "Task", "-c", "todo")
        out, _ = cli("edit", "1", "-t", "bug")
        assert "updated" in out

    def test_edit_untag_not_found(self, cli):
        cli("create", "Task", "-c", "todo")
        _, err = cli("edit", "1", "--untag", "nonexistent", expect_exit=1)
        assert "not found" in err

    def test_edit_nothing_is_noop(self, cli):
        cli("create", "Task", "-c", "todo")
        out, _ = cli("edit", "1")  # no-op: returns unchanged task, exit 0
        assert "updated task-0001" in out

    # -- Tags on ls --

    def test_ls_filter_by_tag(self, cli):
        cli("create", "Tagged", "-t", "bug", "-c", "todo")
        cli("create", "Untagged", "-c", "todo")
        out, _ = cli("ls", "--tag", "bug")
        assert "Tagged" in out
        assert "Untagged" not in out

    def test_ls_shows_tags(self, cli):
        cli("create", "Task", "-t", "bug", "-c", "todo")
        out, _ = cli("ls")
        assert "[bug]" in out

    def test_ls_shows_multiple_tags(self, cli):
        cli("create", "Task", "-t", "bug", "-t", "urgent", "-c", "todo")
        out, _ = cli("ls")
        assert "[bug, urgent]" in out

    def test_ls_tag_filter_not_found(self, cli):
        _, err = cli("ls", "--tag", "nonexistent", expect_exit=1)
        assert "not found" in err

    # -- Tags on show --

    def test_show_displays_tags(self, cli):
        cli("create", "Task", "-t", "bug", "-t", "feature", "-c", "todo")
        out, _ = cli("show", "1")
        assert "Tags:" in out
        assert "bug" in out
        assert "feature" in out


class TestHelp:
    def test_no_args_shows_help(self, capsys):
        try:
            main([])
        except SystemExit as exc:
            assert exc.code == 0


# ---- JSON output ----


class TestJsonOutput:
    """Test --json flag produces valid JSON across command categories."""

    def _json(self, cli, *args):
        """Run CLI with --json and return parsed JSON."""
        import json
        out, _ = cli("--json", *args)
        return json.loads(out)

    # -- Mutations --

    def test_add(self, cli):
        cli("board", "create", "B")
        cli("col", "create", "Todo")
        data = self._json(cli, "create", "My task", "-c", "Todo")
        assert data["ok"] is True
        assert data["data"]["id"] == 1
        assert data["data"]["title"] == "My task"

    def test_edit(self, cli):
        cli("board", "create", "B")
        cli("col", "create", "Todo")
        cli("create", "Original", "-c", "todo")
        data = self._json(cli, "edit", "1", "--title", "Updated")
        assert data["ok"] is True
        assert data["data"]["id"] == 1
        assert data["data"]["title"] == "Updated"

    def test_rm(self, cli):
        cli("board", "create", "B")
        cli("col", "create", "Todo")
        cli("create", "T1", "-c", "todo")
        data = self._json(cli, "rm", "1")
        assert data["ok"] is True
        assert data["data"]["id"] == 1
        assert data["data"]["archived"] is True

    def test_board_create(self, cli):
        data = self._json(cli, "board", "create", "NewBoard")
        assert data["ok"] is True
        assert data["data"]["id"] == 1
        assert data["data"]["name"] == "NewBoard"

    def test_col_create(self, cli):
        cli("board", "create", "B")
        data = self._json(cli, "col", "create", "Backlog")
        assert data["ok"] is True
        assert data["data"]["id"] == 1
        assert data["data"]["name"] == "Backlog"

    def test_project_create(self, cli):
        cli("board", "create", "B")
        data = self._json(cli, "project", "create", "P1")
        assert data["ok"] is True
        assert data["data"]["id"] == 1
        assert data["data"]["name"] == "P1"

    def test_dep_create(self, cli):
        cli("board", "create", "B")
        cli("col", "create", "Todo")
        cli("create", "T1", "-c", "todo")
        cli("create", "T2", "-c", "todo")
        data = self._json(cli, "dep", "create", "1", "2")
        assert data["ok"] is True
        assert data["data"]["task_id"] == 1
        assert data["data"]["depends_on_id"] == 2

    def test_tag_create(self, cli):
        cli("board", "create", "B")
        data = self._json(cli, "tag", "create", "bug")
        assert data["ok"] is True
        assert data["data"]["id"] == 1
        assert data["data"]["name"] == "bug"

    # -- Lists --

    def test_ls(self, cli):
        cli("board", "create", "B")
        cli("col", "create", "Todo")
        cli("create", "Task A", "-c", "todo")
        data = self._json(cli, "ls")
        assert data["ok"] is True
        payload = data["data"]
        assert payload["board"]["name"] == "B"
        assert len(payload["columns"]) == 1
        assert payload["columns"][0]["column"]["name"] == "Todo"
        assert len(payload["columns"][0]["tasks"]) == 1
        assert payload["columns"][0]["tasks"][0]["title"] == "Task A"

    def test_board_ls(self, cli):
        cli("board", "create", "B1")
        data = self._json(cli, "board", "ls")
        assert data["ok"] is True
        payload = data["data"]
        assert isinstance(payload, list)
        assert len(payload) == 1
        assert payload[0]["name"] == "B1"
        assert payload[0]["active"] is True

    def test_col_ls(self, cli):
        cli("board", "create", "B")
        cli("col", "create", "Todo")
        cli("col", "create", "Done")
        data = self._json(cli, "col", "ls")
        assert data["ok"] is True
        assert isinstance(data["data"], list)
        assert len(data["data"]) == 2

    def test_project_ls(self, cli):
        cli("board", "create", "B")
        cli("project", "create", "P1")
        data = self._json(cli, "project", "ls")
        assert data["ok"] is True
        payload = data["data"]
        assert isinstance(payload, list)
        assert payload[0]["name"] == "P1"

    def test_log_empty(self, cli):
        cli("board", "create", "B")
        cli("col", "create", "Todo")
        cli("create", "T1", "-c", "todo")
        data = self._json(cli, "log", "1")
        assert data["ok"] is True
        assert isinstance(data["data"], list)

    def test_group_ls(self, cli):
        cli("board", "create", "B")
        cli("col", "create", "Todo")
        cli("project", "create", "P1")
        cli("group", "create", "G1", "-p", "P1")
        data = self._json(cli, "group", "ls")
        assert data["ok"] is True
        payload = data["data"]
        assert isinstance(payload, list)
        assert payload[0]["title"] == "G1"

    def test_tag_ls(self, cli):
        cli("board", "create", "B")
        cli("tag", "create", "bug")
        cli("tag", "create", "feature")
        data = self._json(cli, "tag", "ls")
        assert data["ok"] is True
        payload = data["data"]
        assert isinstance(payload, list)
        assert len(payload) == 2
        assert payload[0]["name"] == "bug"

    # -- Details --

    def test_show(self, cli):
        cli("board", "create", "B")
        cli("col", "create", "Todo")
        cli("create", "Task A", "--priority", "3", "-c", "todo")
        data = self._json(cli, "show", "1")
        assert data["ok"] is True
        payload = data["data"]
        assert payload["title"] == "Task A"
        assert payload["priority"] == 3
        assert "column" in payload
        assert payload["column"]["name"] == "Todo"
        assert "group_id" in payload

    def test_show_with_tags(self, cli):
        cli("board", "create", "B")
        cli("col", "create", "Todo")
        cli("create", "Task A", "-t", "bug", "-t", "feature", "-c", "todo")
        data = self._json(cli, "show", "1")
        assert data["ok"] is True
        payload = data["data"]
        assert len(payload["tags"]) == 2
        assert payload["tags"][0]["name"] == "bug"
        assert payload["tags"][1]["name"] == "feature"

    def test_project_show(self, cli):
        cli("board", "create", "B")
        cli("col", "create", "Todo")
        cli("project", "create", "P1", "-d", "desc")
        cli("create", "T1", "-p", "P1", "-c", "todo")
        data = self._json(cli, "project", "show", "P1")
        assert data["ok"] is True
        payload = data["data"]
        assert payload["name"] == "P1"
        assert payload["description"] == "desc"
        assert len(payload["tasks"]) == 1

    def test_group_show(self, cli):
        cli("board", "create", "B")
        cli("col", "create", "Todo")
        cli("project", "create", "P1")
        cli("group", "create", "G1", "-p", "P1")
        data = self._json(cli, "group", "show", "G1")
        assert data["ok"] is True
        assert data["data"]["title"] == "G1"

    # -- Moves --

    def test_mv_within_board(self, cli):
        cli("board", "create", "B")
        cli("col", "create", "Todo")
        cli("col", "create", "Done")
        cli("create", "T1", "-c", "todo")
        data = self._json(cli, "mv", "1", "Done")
        assert data["ok"] is True
        assert data["data"]["id"] == 1

    def test_transfer_cross_board(self, cli):
        cli("board", "create", "B1")
        cli("col", "create", "Todo")
        cli("create", "T1", "-c", "todo")
        cli("board", "create", "B2")
        cli("col", "create", "Inbox")
        data = self._json(cli, "transfer", "1", "--board", "B2", "--column", "Inbox")
        assert data["ok"] is True
        assert data["data"]["task"]["title"] == "T1"
        assert data["data"]["source_task_id"] == 1

    def test_transfer_dry_run(self, cli):
        cli("board", "create", "B1")
        cli("col", "create", "Todo")
        cli("create", "T1", "-c", "todo")
        cli("board", "create", "B2")
        cli("col", "create", "Inbox")
        data = self._json(cli, "transfer", "1", "--board", "B2", "--column", "Inbox", "--dry-run")
        assert data["ok"] is True
        payload = data["data"]
        assert payload["can_move"] is True
        assert payload["dependency_ids"] == []
        assert payload["blocking_reason"] is None
        assert payload["is_archived"] is False

    def test_mv_project_only_use_edit(self, cli):
        cli("board", "create", "B")
        cli("col", "create", "Todo")
        cli("project", "create", "P1")
        cli("create", "T1", "-c", "todo")
        data = self._json(cli, "edit", "1", "--project", "P1")
        assert data["ok"] is True
        assert data["data"]["id"] == 1
        assert data["data"]["project_id"] == 1

    # -- Edit edge case --

    def test_edit_no_changes(self, cli):
        import json
        cli("board", "create", "B")
        cli("col", "create", "Todo")
        cli("create", "T1", "-c", "todo")
        out, _ = cli("--json", "edit", "1")
        data = json.loads(out)
        assert data["ok"] is True
        assert data["data"]["id"] == 1

    # -- Log with entries --

    def test_log_with_history(self, cli):
        cli("board", "create", "B")
        cli("col", "create", "Todo")
        cli("create", "T1", "-c", "todo")
        cli("edit", "1", "--title", "Updated")
        data = self._json(cli, "log", "1")
        assert data["ok"] is True
        payload = data["data"]
        assert isinstance(payload, list)
        assert len(payload) >= 1
        assert payload[0]["field"] == "title"

    # -- Export --

    def test_export(self, cli):
        cli("board", "create", "B")
        cli("col", "create", "Todo")
        cli("create", "T1", "-c", "todo")
        data = self._json(cli, "export")
        assert data["ok"] is True
        payload = data["data"]
        assert "markdown" in payload
        assert "# Sticky Notes Export" in payload["markdown"]

    # -- Group assign/unassign --

    def test_group_assign(self, cli):
        cli("board", "create", "B")
        cli("col", "create", "Todo")
        cli("project", "create", "P1")
        cli("group", "create", "G1", "-p", "P1")
        cli("create", "T1", "-p", "P1", "-c", "todo")
        data = self._json(cli, "group", "assign", "1", "G1", "-p", "P1")
        assert data["ok"] is True
        assert data["data"]["task"]["id"] == 1
        assert data["data"]["group_id"] == 1

    def test_group_unassign(self, cli):
        cli("board", "create", "B")
        cli("col", "create", "Todo")
        cli("project", "create", "P1")
        cli("group", "create", "G1", "-p", "P1")
        cli("create", "T1", "-p", "P1", "-c", "todo")
        cli("group", "assign", "1", "G1", "-p", "P1")
        data = self._json(cli, "group", "unassign", "1")
        assert data["ok"] is True
        assert data["data"]["id"] == 1

    # -- Error in JSON mode --

    def test_error_json(self, cli):
        import json
        cli("board", "create", "B")
        _, err = cli("--json", "show", "999", expect_exit=1)
        data = json.loads(err)
        assert data["ok"] is False
        assert "error" in data
        assert "code" in data


class TestErrorHandlingExtended:
    """Tests for CLI-level exception handling added in the general review."""

    def test_keyboard_interrupt_exits_130(self, db_path, monkeypatch):
        """KeyboardInterrupt during a command must exit 130 without output."""
        import json
        from sticky_notes.cli import main, HANDLERS

        original = HANDLERS["ls"]
        monkeypatch.setitem(HANDLERS, "ls", lambda *a, **kw: (_ for _ in ()).throw(KeyboardInterrupt()))
        with pytest.raises(SystemExit) as exc_info:
            main(["--db", str(db_path), "--json", "ls"])
        monkeypatch.setitem(HANDLERS, "ls", original)
        assert exc_info.value.code == 130

    def test_operational_error_exits_2(self, db_path, capsys, monkeypatch):
        """sqlite3.OperationalError must print a friendly message and exit 2."""
        import sqlite3
        from sticky_notes.cli import main, HANDLERS

        original = HANDLERS["ls"]
        monkeypatch.setitem(HANDLERS, "ls", lambda *a, **kw: (_ for _ in ()).throw(
            sqlite3.OperationalError("disk I/O error")
        ))
        with pytest.raises(SystemExit) as exc_info:
            main(["--db", str(db_path), "ls"])
        captured = capsys.readouterr()
        monkeypatch.setitem(HANDLERS, "ls", original)
        assert exc_info.value.code == 2
        assert "database error" in captured.err
        assert "disk I/O error" in captured.err

    def test_operational_error_json_exits_2(self, db_path, capsys, monkeypatch):
        """sqlite3.OperationalError in --json mode emits JSON error and exits 2."""
        import json
        import sqlite3
        from sticky_notes.cli import main, HANDLERS

        original = HANDLERS["ls"]
        monkeypatch.setitem(HANDLERS, "ls", lambda *a, **kw: (_ for _ in ()).throw(
            sqlite3.OperationalError("disk I/O error")
        ))
        with pytest.raises(SystemExit) as exc_info:
            main(["--db", str(db_path), "--json", "ls"])
        captured = capsys.readouterr()
        monkeypatch.setitem(HANDLERS, "ls", original)
        assert exc_info.value.code == 2
        data = json.loads(captured.err)
        assert data["ok"] is False
        assert "database error" in data["error"]


class TestExportParentDir:
    def test_export_creates_parent_dirs(self, cli, tmp_path):
        cli("board", "create", "B")
        output = tmp_path / "new" / "sub" / "out.md"
        out, _ = cli("export", "-o", str(output))
        assert output.exists()
        assert "# Sticky Notes Export" in output.read_text()
