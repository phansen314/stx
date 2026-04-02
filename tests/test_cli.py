from __future__ import annotations

import pytest
from pathlib import Path

from sticky_notes.active_board import (
    active_board_path,
    get_active_board_id,
    set_active_board_id,
)
from sticky_notes.cli import (
    format_timestamp,
    main,
    parse_date,
    parse_task_num,
)
from sticky_notes.formatting import format_priority, format_task_num


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
        assert "renamed board -> 'staging'" in out

    def test_archive(self, cli):
        cli("board", "create", "dev")
        out, _ = cli("board", "archive")
        assert "archived board" in out

    def test_use_nonexistent(self, cli):
        _, err = cli("board", "use", "nope", expect_exit=1)
        assert "error:" in err


# ---- Column commands ----


class TestColumnCommands:
    def test_add(self, cli):
        cli("board", "create", "dev")
        out, _ = cli("col", "add", "backlog")
        assert "created column 'backlog'" in out

    def test_add_with_position(self, cli):
        cli("board", "create", "dev")
        cli("col", "add", "backlog", "--pos", "0")
        cli("col", "add", "done", "--pos", "2")
        cli("col", "add", "in progress", "--pos", "1")
        out, _ = cli("col", "ls")
        lines = out.strip().split("\n")
        assert "backlog" in lines[0]
        assert "in progress" in lines[1]
        assert "done" in lines[2]

    def test_ls(self, cli):
        cli("board", "create", "dev")
        cli("col", "add", "todo")
        cli("col", "add", "done", "--pos", "1")
        out, _ = cli("col", "ls")
        assert "todo" in out
        assert "done" in out

    def test_ls_empty(self, cli):
        cli("board", "create", "dev")
        out, _ = cli("col", "ls")
        assert "no columns" in out

    def test_rename(self, cli):
        cli("board", "create", "dev")
        cli("col", "add", "todo")
        out, _ = cli("col", "rename", "todo", "backlog")
        assert "renamed column 'todo' -> 'backlog'" in out

    def test_archive(self, cli):
        cli("board", "create", "dev")
        cli("col", "add", "todo")
        out, _ = cli("col", "archive", "todo")
        assert "archived column 'todo'" in out


# ---- Task shortcuts ----


class TestTaskCommands:
    @pytest.fixture(autouse=True)
    def _setup(self, cli):
        cli("board", "create", "dev")
        cli("col", "add", "todo", "--pos", "0")
        cli("col", "add", "in progress", "--pos", "1")
        cli("col", "add", "done", "--pos", "2")

    def test_add_default_column(self, cli):
        out, _ = cli("add", "Fix login bug")
        assert "created task-0001" in out

    def test_add_explicit_column(self, cli):
        out, _ = cli("add", "My task", "-c", "in progress")
        assert "created task-0001" in out

    def test_add_with_project(self, cli):
        cli("project", "create", "backend")
        out, _ = cli("add", "Fix bug", "-p", "backend")
        assert "created task-0001" in out

    def test_add_with_priority_and_due(self, cli):
        out, _ = cli("add", "Important", "--priority", "3", "--due", "2026-04-01")
        assert "created task-0001" in out

    def test_add_with_desc(self, cli):
        out, _ = cli("add", "Fix it", "-d", "Full description here")
        assert "created task-0001" in out

    def test_ls_grouped_by_column(self, cli):
        cli("add", "Task A")
        cli("add", "Task B", "-c", "in progress")
        out, _ = cli("ls")
        assert "== todo ==" in out
        assert "Task A" in out
        assert "== in progress ==" in out
        assert "Task B" in out
        assert "== done ==" in out
        assert "(empty)" in out

    def test_ls_shows_project(self, cli):
        cli("project", "create", "backend")
        cli("add", "Fix bug", "-p", "backend")
        out, _ = cli("ls")
        assert "@backend" in out

    def test_ls_shows_priority(self, cli):
        cli("add", "Fix bug", "--priority", "3")
        out, _ = cli("ls")
        assert "[P3]" in out

    def test_show(self, cli):
        cli("add", "Fix login bug", "--priority", "2", "--due", "2026-04-01")
        out, _ = cli("show", "1")
        assert "task-0001" in out
        assert "Fix login bug" in out
        assert "Priority:    2" in out
        assert "Due:         2026-04-01" in out
        assert "Column:      todo" in out

    def test_show_with_project(self, cli):
        cli("project", "create", "backend")
        cli("add", "Fix bug", "-p", "backend")
        out, _ = cli("show", "1")
        assert "Project:     backend" in out

    def test_show_with_deps(self, cli):
        cli("add", "Task A")
        cli("add", "Task B")
        cli("dep", "add", "2", "1")
        out, _ = cli("show", "2")
        assert "Blocked by:  task-0001" in out
        # Also check the "Blocks" line from the other side
        out2, _ = cli("show", "1")
        assert "Blocks:      task-0002" in out2

    def test_show_with_description(self, cli):
        cli("add", "Fix bug", "-d", "Detailed description")
        out, _ = cli("show", "1")
        assert "Description:" in out
        assert "Detailed description" in out

    def test_edit_title(self, cli):
        cli("add", "Old title")
        out, _ = cli("edit", "1", "--title", "New title")
        assert "updated task-0001" in out
        show_out, _ = cli("show", "1")
        assert "New title" in show_out

    def test_edit_priority(self, cli):
        cli("add", "Task")
        cli("edit", "1", "--priority", "5")
        out, _ = cli("show", "1")
        assert "Priority:    5" in out

    def test_edit_desc(self, cli):
        cli("add", "Task")
        cli("edit", "1", "-d", "new desc")
        out, _ = cli("show", "1")
        assert "new desc" in out

    def test_edit_due(self, cli):
        cli("add", "Task")
        cli("edit", "1", "--due", "2026-06-01")
        out, _ = cli("show", "1")
        assert "Due:         2026-06-01" in out

    def test_edit_project(self, cli):
        cli("project", "create", "backend")
        cli("add", "Task")
        cli("edit", "1", "-p", "backend")
        out, _ = cli("show", "1")
        assert "Project:     backend" in out

    def test_edit_nothing(self, cli):
        cli("add", "Task")
        _, err = cli("edit", "1", expect_exit=1)
        assert "nothing to change" in err

    def test_mv(self, cli):
        cli("add", "Task A")
        out, _ = cli("mv", "1", "in progress")
        assert "moved task-0001 -> in progress" in out

    def test_mv_case_insensitive(self, cli):
        cli("add", "Task A")
        out, _ = cli("mv", "1", "In Progress")
        assert "moved task-0001 -> in progress" in out

    def test_done(self, cli):
        cli("add", "Task A")
        out, _ = cli("done", "1")
        assert "moved task-0001 -> done" in out

    def test_rm(self, cli):
        cli("add", "Task A")
        out, _ = cli("rm", "1")
        assert "archived task-0001" in out

    def test_rm_hides_from_ls(self, cli):
        cli("add", "Task A")
        cli("rm", "1")
        out, _ = cli("ls")
        assert "Task A" not in out

    def test_log(self, cli):
        cli("add", "Task A")
        cli("edit", "1", "--title", "Task B")
        out, _ = cli("log", "1")
        assert "title:" in out
        assert "Task A" in out
        assert "Task B" in out
        assert "(cli)" in out

    def test_log_empty(self, cli):
        cli("add", "Task A")
        out, _ = cli("log", "1")
        assert "no history" in out

    def test_show_nonexistent(self, cli):
        _, err = cli("show", "999", expect_exit=1)
        assert "error:" in err

    def test_task_num_formats(self, cli):
        cli("add", "Task A")
        out1, _ = cli("show", "task-0001")
        out2, _ = cli("show", "#1")
        out3, _ = cli("show", "0001")
        assert "Task A" in out1
        assert "Task A" in out2
        assert "Task A" in out3

    def test_show_by_title(self, cli):
        cli("add", "Fix login bug")
        out, _ = cli("show", "Fix login bug")
        assert "task-0001" in out
        assert "Fix login bug" in out

    def test_show_by_title_not_found(self, cli):
        _, err = cli("show", "nonexistent title", expect_exit=1)
        assert "error:" in err

    def test_dep_add_by_title(self, cli):
        cli("add", "Task A")
        cli("add", "Task B")
        out, _ = cli("dep", "add", "Task B", "Task A")
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
        cli("col", "add", "todo")
        cli("project", "create", "backend", "-d", "API layer")
        cli("add", "Fix bug", "-p", "backend")
        out, _ = cli("project", "show", "backend")
        assert "backend" in out
        assert "API layer" in out
        assert "Tasks: 1" in out
        assert "Fix bug" in out

    def test_archive(self, cli):
        cli("project", "create", "backend")
        out, _ = cli("project", "archive", "backend")
        assert "archived project 'backend'" in out


# ---- Dependency commands ----


class TestDependencyCommands:
    @pytest.fixture(autouse=True)
    def _setup(self, cli):
        cli("board", "create", "dev")
        cli("col", "add", "todo")

    def test_add(self, cli):
        cli("add", "Task A")
        cli("add", "Task B")
        out, _ = cli("dep", "add", "2", "1")
        assert "task-0002 now blocked by task-0001" in out

    def test_rm(self, cli):
        cli("add", "Task A")
        cli("add", "Task B")
        cli("dep", "add", "2", "1")
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

    def test_no_columns_add(self, cli):
        cli("board", "create", "dev")
        _, err = cli("add", "Task", expect_exit=1)
        assert "no columns" in err

    def test_column_not_found(self, cli):
        cli("board", "create", "dev")
        cli("col", "add", "todo")
        _, err = cli("add", "Task", "-c", "nonexistent", expect_exit=1)
        assert "not found" in err

    def test_project_not_found(self, cli):
        cli("board", "create", "dev")
        cli("col", "add", "todo")
        _, err = cli("add", "Task", "-p", "nonexistent", expect_exit=1)
        assert "not found" in err

    def test_done_no_columns(self, cli):
        cli("board", "create", "dev")
        cli("col", "add", "todo")
        cli("add", "Task")
        cli("col", "archive", "todo")
        _, err = cli("done", "1", expect_exit=1)
        assert "no columns" in err


# ---- Board flag override ----


class TestBoardFlag:
    def test_board_flag(self, cli):
        cli("board", "create", "dev")
        cli("board", "create", "ops")
        cli("-b", "dev", "col", "add", "todo")
        out, _ = cli("-b", "dev", "col", "ls")
        assert "todo" in out

    def test_board_flag_overrides_active(self, cli):
        cli("board", "create", "dev")
        cli("board", "create", "ops")
        # ops is now active (last created)
        cli("-b", "dev", "col", "add", "backlog")
        out, _ = cli("-b", "dev", "col", "ls")
        assert "backlog" in out
        # ops has no columns
        out2, _ = cli("col", "ls")
        assert "no columns" in out2


# ---- Help output ----


class TestLsFilters:
    def _setup_board(self, cli):
        cli("board", "create", "work")
        cli("col", "add", "backlog")
        cli("col", "add", "doing")
        cli("project", "create", "alpha")

    def test_filter_by_column(self, cli):
        self._setup_board(cli)
        cli("add", "task1", "-c", "backlog")
        cli("add", "task2", "-c", "doing")
        out, _ = cli("ls", "-c", "backlog")
        assert "task1" in out
        assert "task2" not in out or "task2" not in out.split("== backlog ==")[0]

    def test_filter_by_project(self, cli):
        self._setup_board(cli)
        cli("add", "task1", "-p", "alpha")
        cli("add", "task2")
        out, _ = cli("ls", "-p", "alpha")
        assert "task1" in out
        # task2 not in any non-empty column section
        lines = [l for l in out.splitlines() if "task2" in l]
        assert len(lines) == 0

    def test_filter_by_priority(self, cli):
        self._setup_board(cli)
        cli("add", "low", "--priority", "1")
        cli("add", "high", "--priority", "3")
        out, _ = cli("ls", "-P", "3")
        assert "high" in out
        lines = [l for l in out.splitlines() if "low" in l]
        assert len(lines) == 0

    def test_filter_by_search(self, cli):
        self._setup_board(cli)
        cli("add", "Fix login bug")
        cli("add", "Add search feature")
        out, _ = cli("ls", "-s", "login")
        assert "Fix login bug" in out
        lines = [l for l in out.splitlines() if "search feature" in l]
        assert len(lines) == 0

    def test_combined_filters(self, cli):
        self._setup_board(cli)
        cli("add", "task1", "-c", "backlog", "--priority", "3")
        cli("add", "task2", "-c", "backlog", "--priority", "1")
        cli("add", "task3", "-c", "doing", "--priority", "3")
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
        cli("col", "add", "todo", "--pos", "0")
        cli("col", "add", "done", "--pos", "1")

    def test_mv_to_board(self, cli):
        cli("board", "create", "ops")
        cli("board", "use", "ops")
        cli("col", "add", "backlog")
        cli("board", "use", "dev")
        cli("add", "Task A")
        out, _ = cli("mv", "1", "backlog", "--board", "ops")
        assert 'board "ops"' in out
        assert 'column "backlog"' in out

    def test_mv_to_board_with_project(self, cli):
        cli("board", "create", "ops")
        cli("board", "use", "ops")
        cli("col", "add", "backlog")
        cli("project", "create", "infra")
        cli("board", "use", "dev")
        cli("add", "Task A")
        out, _ = cli("mv", "1", "backlog", "--board", "ops", "-p", "infra")
        assert 'board "ops"' in out

    def test_mv_to_board_no_column_fails(self, cli):
        cli("board", "create", "ops")
        cli("board", "use", "dev")
        cli("add", "Task A")
        _, err = cli("mv", "1", "--board", "ops", expect_exit=1)
        assert "column name required" in err

    def test_mv_project_only(self, cli):
        cli("project", "create", "backend")
        cli("add", "Task A")
        out, _ = cli("mv", "1", "-p", "backend")
        assert "project -> backend" in out

    def test_mv_no_args_fails(self, cli):
        cli("add", "Task A")
        _, err = cli("mv", "1", expect_exit=1)
        assert "specify a column" in err

    def test_mv_dry_run(self, cli):
        cli("board", "create", "ops")
        cli("board", "use", "ops")
        cli("col", "add", "backlog")
        cli("board", "use", "dev")
        cli("add", "Task A")
        out, _ = cli("mv", "1", "backlog", "--board", "ops", "--dry-run")
        assert "dry-run" in out
        assert "move OK" in out

    def test_mv_dry_run_with_deps(self, cli):
        cli("board", "create", "ops")
        cli("board", "use", "ops")
        cli("col", "add", "backlog")
        cli("board", "use", "dev")
        cli("add", "Task A")
        cli("add", "Task B")
        cli("dep", "add", "2", "1")
        out, _ = cli("mv", "1", "backlog", "--board", "ops", "--dry-run")
        assert "dependencies" in out
        assert "FAIL" in out


class TestGroupCLI:
    """Fixture `cli` provides a helper that always passes --db to a temp DB.
    Each test creates its own board/project/column setup."""

    @pytest.fixture(autouse=True)
    def _setup(self, cli):
        self.cli = cli
        cli("board", "create", "dev")
        cli("col", "add", "todo")
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
        _, err = self.cli("group", "create", "Orphan", expect_exit=1)
        assert "--project is required" in err

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
        self.cli("add", "Fix bug", "--project", "sprint1")
        self.cli("group", "assign", "task-0001", "Frontend", "--project", "sprint1")
        out, _ = self.cli("group", "ls", "--project", "sprint1", "--tree")
        assert "Frontend" in out
        assert "Components" in out
        assert "task-0001" in out

    def test_show_group(self):
        self.cli("group", "create", "Frontend", "--project", "sprint1")
        self.cli("add", "Fix bug", "--project", "sprint1")
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
        out, _ = self.cli("group", "archive", "Frontend", "--project", "sprint1")
        assert "archived group 'Frontend'" in out

    def test_archive_orphans_tasks(self):
        self.cli("group", "create", "Frontend", "--project", "sprint1")
        self.cli("add", "Fix bug", "--project", "sprint1")
        self.cli("group", "assign", "task-0001", "Frontend", "--project", "sprint1")
        self.cli("group", "archive", "Frontend", "--project", "sprint1")
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
        out, _ = self.cli("group", "mv", "Child", "--parent", "none", "--project", "sprint1")
        assert "promoted" in out

    def test_assign_task(self):
        self.cli("group", "create", "Frontend", "--project", "sprint1")
        self.cli("add", "Fix bug", "--project", "sprint1")
        out, _ = self.cli("group", "assign", "task-0001", "Frontend", "--project", "sprint1")
        assert "assigned task-0001 to group 'Frontend'" in out

    def test_assign_auto_sets_project(self):
        self.cli("group", "create", "Frontend", "--project", "sprint1")
        self.cli("add", "No project task")
        self.cli("group", "assign", "task-0001", "Frontend", "--project", "sprint1")
        out, _ = self.cli("show", "task-0001")
        assert "sprint1" in out

    def test_assign_cross_project_raises(self):
        self.cli("project", "create", "sprint2")
        self.cli("group", "create", "Frontend", "--project", "sprint1")
        self.cli("add", "Task", "--project", "sprint2")
        _, err = self.cli("group", "assign", "task-0001", "Frontend", "--project", "sprint1", expect_exit=1)
        assert "project" in err

    def test_unassign_task(self):
        self.cli("group", "create", "Frontend", "--project", "sprint1")
        self.cli("add", "Fix bug", "--project", "sprint1")
        self.cli("group", "assign", "task-0001", "Frontend", "--project", "sprint1")
        out, _ = self.cli("group", "unassign", "task-0001")
        assert "unassigned" in out

    def test_show_displays_group(self):
        self.cli("group", "create", "Frontend", "--project", "sprint1")
        self.cli("add", "Fix bug", "--project", "sprint1")
        self.cli("group", "assign", "task-0001", "Frontend", "--project", "sprint1")
        out, _ = self.cli("show", "task-0001")
        assert "Group:" in out
        assert "Frontend" in out

    def test_ls_group_filter(self):
        self.cli("group", "create", "Frontend", "--project", "sprint1")
        self.cli("add", "Grouped", "--project", "sprint1")
        self.cli("add", "Ungrouped", "--project", "sprint1")
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
        cli("col", "add", "Todo")
        data = self._json(cli, "add", "My task")
        assert data["ok"] is True
        assert data["id"] == 1

    def test_edit(self, cli):
        cli("board", "create", "B")
        cli("col", "add", "Todo")
        cli("add", "Original")
        data = self._json(cli, "edit", "1", "--title", "Updated")
        assert data["ok"] is True
        assert data["id"] == 1

    def test_done(self, cli):
        cli("board", "create", "B")
        cli("col", "add", "Todo")
        cli("col", "add", "Done")
        cli("add", "T1")
        data = self._json(cli, "done", "1")
        assert data["ok"] is True
        assert data["id"] == 1

    def test_rm(self, cli):
        cli("board", "create", "B")
        cli("col", "add", "Todo")
        cli("add", "T1")
        data = self._json(cli, "rm", "1")
        assert data["ok"] is True
        assert data["id"] == 1

    def test_board_create(self, cli):
        data = self._json(cli, "board", "create", "NewBoard")
        assert data["ok"] is True
        assert data["id"] == 1

    def test_col_add(self, cli):
        cli("board", "create", "B")
        data = self._json(cli, "col", "add", "Backlog")
        assert data["ok"] is True
        assert data["id"] == 1

    def test_project_create(self, cli):
        cli("board", "create", "B")
        data = self._json(cli, "project", "create", "P1")
        assert data["ok"] is True
        assert data["id"] == 1

    def test_dep_add(self, cli):
        cli("board", "create", "B")
        cli("col", "add", "Todo")
        cli("add", "T1")
        cli("add", "T2")
        data = self._json(cli, "dep", "add", "1", "2")
        assert data["ok"] is True
        assert data["task_id"] == 1
        assert data["depends_on_id"] == 2

    # -- Lists --

    def test_ls(self, cli):
        cli("board", "create", "B")
        cli("col", "add", "Todo")
        cli("add", "Task A")
        data = self._json(cli, "ls")
        assert data["board"] == "B"
        assert len(data["columns"]) == 1
        assert data["columns"][0]["name"] == "Todo"
        assert len(data["columns"][0]["tasks"]) == 1
        assert data["columns"][0]["tasks"][0]["title"] == "Task A"

    def test_board_ls(self, cli):
        cli("board", "create", "B1")
        data = self._json(cli, "board", "ls")
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["name"] == "B1"
        assert data[0]["active"] is True

    def test_col_ls(self, cli):
        cli("board", "create", "B")
        cli("col", "add", "Todo")
        cli("col", "add", "Done")
        data = self._json(cli, "col", "ls")
        assert isinstance(data, list)
        assert len(data) == 2

    def test_project_ls(self, cli):
        cli("board", "create", "B")
        cli("project", "create", "P1")
        data = self._json(cli, "project", "ls")
        assert isinstance(data, list)
        assert data[0]["name"] == "P1"

    def test_log_empty(self, cli):
        cli("board", "create", "B")
        cli("col", "add", "Todo")
        cli("add", "T1")
        data = self._json(cli, "log", "1")
        assert isinstance(data, list)

    def test_group_ls(self, cli):
        cli("board", "create", "B")
        cli("col", "add", "Todo")
        cli("project", "create", "P1")
        cli("group", "create", "G1", "-p", "P1")
        data = self._json(cli, "group", "ls")
        assert isinstance(data, list)
        assert data[0]["title"] == "G1"

    # -- Details --

    def test_show(self, cli):
        cli("board", "create", "B")
        cli("col", "add", "Todo")
        cli("add", "Task A", "--priority", "3")
        data = self._json(cli, "show", "1")
        assert data["title"] == "Task A"
        assert data["priority"] == 3
        assert "column" in data
        assert data["column"]["name"] == "Todo"
        assert "group_id" in data

    def test_project_show(self, cli):
        cli("board", "create", "B")
        cli("col", "add", "Todo")
        cli("project", "create", "P1", "-d", "desc")
        cli("add", "T1", "-p", "P1")
        data = self._json(cli, "project", "show", "P1")
        assert data["name"] == "P1"
        assert data["description"] == "desc"
        assert len(data["tasks"]) == 1

    def test_group_show(self, cli):
        cli("board", "create", "B")
        cli("col", "add", "Todo")
        cli("project", "create", "P1")
        cli("group", "create", "G1", "-p", "P1")
        data = self._json(cli, "group", "show", "G1")
        assert data["title"] == "G1"

    # -- Moves --

    def test_mv_within_board(self, cli):
        cli("board", "create", "B")
        cli("col", "add", "Todo")
        cli("col", "add", "Done")
        cli("add", "T1")
        data = self._json(cli, "mv", "1", "Done")
        assert data["ok"] is True
        assert data["id"] == 1

    def test_mv_cross_board(self, cli):
        cli("board", "create", "B1")
        cli("col", "add", "Todo")
        cli("add", "T1")
        cli("board", "create", "B2")
        cli("col", "add", "Inbox")
        data = self._json(cli, "mv", "1", "Inbox", "--board", "B2")
        assert data["ok"] is True
        assert data["id"] == 1
        assert "new_id" in data

    def test_mv_dry_run(self, cli):
        cli("board", "create", "B1")
        cli("col", "add", "Todo")
        cli("add", "T1")
        cli("board", "create", "B2")
        cli("col", "add", "Inbox")
        data = self._json(cli, "mv", "1", "Inbox", "--board", "B2", "--dry-run")
        assert data["dry_run"] is True
        assert data["can_move"] is True
        assert data["dependency_ids"] == []

    def test_mv_project_only(self, cli):
        cli("board", "create", "B")
        cli("col", "add", "Todo")
        cli("project", "create", "P1")
        cli("add", "T1")
        data = self._json(cli, "mv", "1", "--project", "P1")
        assert data["ok"] is True
        assert data["id"] == 1

    # -- Edit edge case --

    def test_edit_no_changes(self, cli):
        import json
        cli("board", "create", "B")
        cli("col", "add", "Todo")
        cli("add", "T1")
        out, _ = cli("--json", "edit", "1", expect_exit=1)
        data = json.loads(out)
        assert data["ok"] is False
        assert "nothing to change" in data["error"]

    # -- Log with entries --

    def test_log_with_history(self, cli):
        cli("board", "create", "B")
        cli("col", "add", "Todo")
        cli("add", "T1")
        cli("edit", "1", "--title", "Updated")
        data = self._json(cli, "log", "1")
        assert isinstance(data, list)
        assert len(data) >= 1
        assert data[0]["field"] == "title"

    # -- Export --

    def test_export(self, cli):
        cli("board", "create", "B")
        cli("col", "add", "Todo")
        cli("add", "T1")
        data = self._json(cli, "export")
        assert "markdown" in data
        assert "# B" in data["markdown"]

    # -- Group assign/unassign --

    def test_group_assign(self, cli):
        cli("board", "create", "B")
        cli("col", "add", "Todo")
        cli("project", "create", "P1")
        cli("group", "create", "G1", "-p", "P1")
        cli("add", "T1", "-p", "P1")
        data = self._json(cli, "group", "assign", "1", "G1", "-p", "P1")
        assert data["ok"] is True
        assert data["task_id"] == 1
        assert data["group_id"] == 1

    def test_group_unassign(self, cli):
        cli("board", "create", "B")
        cli("col", "add", "Todo")
        cli("project", "create", "P1")
        cli("group", "create", "G1", "-p", "P1")
        cli("add", "T1", "-p", "P1")
        cli("group", "assign", "1", "G1", "-p", "P1")
        data = self._json(cli, "group", "unassign", "1")
        assert data["ok"] is True
        assert data["task_id"] == 1

    # -- Error in JSON mode --

    def test_error_json(self, cli):
        import json
        cli("board", "create", "B")
        out, _ = cli("--json", "show", "999", expect_exit=1)
        data = json.loads(out)
        assert data["ok"] is False
        assert "error" in data
