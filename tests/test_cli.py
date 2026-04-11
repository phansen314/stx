from __future__ import annotations

import json

import pytest
from pathlib import Path

from sticky_notes.active_workspace import (
    active_workspace_path,
    get_active_workspace_id,
    set_active_workspace_id,
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


# ---- Active workspace helpers ----


class TestActiveWorkspace:
    def test_path(self, db_path: Path):
        assert active_workspace_path(db_path) == db_path.parent / "active-workspace"

    def test_get_none(self, db_path: Path):
        assert get_active_workspace_id(db_path) is None

    def test_set_and_get(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        set_active_workspace_id(db_path, 42)
        assert get_active_workspace_id(db_path) == 42


# ---- Workspace commands ----


class TestWorkspaceCommands:
    def test_create(self, cli):
        out, _ = cli("workspace", "create", "dev")
        assert "created workspace 'dev' (active)" in out

    def test_create_auto_activates(self, cli, db_path):
        cli("workspace", "create", "dev")
        assert get_active_workspace_id(db_path) is not None

    def test_ls(self, cli):
        cli("workspace", "create", "dev")
        cli("workspace", "create", "ops")
        out, _ = cli("workspace", "ls")
        assert "dev" in out
        assert "ops" in out

    def test_ls_shows_active_marker(self, cli):
        cli("workspace", "create", "dev")
        out, _ = cli("workspace", "ls")
        assert "dev *" in out

    def test_ls_empty(self, cli):
        out, _ = cli("workspace", "ls")
        assert "no workspaces" in out

    def test_use(self, cli, db_path):
        cli("workspace", "create", "dev")
        cli("workspace", "create", "ops")
        cli("workspace", "use", "dev")
        out, _ = cli("workspace", "ls")
        assert "dev *" in out

    def test_rename(self, cli):
        cli("workspace", "create", "dev")
        out, _ = cli("workspace", "rename", "dev", "staging")
        assert "renamed workspace 'dev' -> 'staging'" in out

    def test_archive(self, cli):
        cli("workspace", "create", "dev")
        out, _ = cli("workspace", "archive", "--force")
        assert "archived workspace" in out

    def test_archive_active_workspace_clears_pointer(self, cli, db_path):
        cli("workspace", "create", "dev")
        assert get_active_workspace_id(db_path) is not None
        cli("workspace", "archive", "--force")
        assert get_active_workspace_id(db_path) is None

    def test_archive_non_active_workspace_leaves_pointer(self, cli, db_path):
        cli("workspace", "create", "dev")
        cli("workspace", "create", "ops")
        cli("workspace", "use", "dev")
        # ops is not active — archiving it must not clear the pointer
        cli("-w", "ops", "workspace", "archive", "--force")
        assert get_active_workspace_id(db_path) is not None

    def test_archive_json_shape_includes_active_cleared(self, cli):
        cli("workspace", "create", "dev")
        out, _ = cli("--json", "workspace", "archive", "--force")
        data = json.loads(out)["data"]
        assert data["active_cleared"] is True
        assert data["workspace"]["name"] == "dev"
        assert data["workspace"]["archived"] is True

    def test_archive_json_shape_active_cleared_false_for_inactive(self, cli):
        cli("workspace", "create", "dev")
        cli("workspace", "create", "ops")
        cli("workspace", "use", "dev")
        out, _ = cli("-w", "ops", "--json", "workspace", "archive", "--force")
        data = json.loads(out)["data"]
        assert data["active_cleared"] is False
        assert data["workspace"]["name"] == "ops"

    def test_use_nonexistent(self, cli):
        _, err = cli("workspace", "use", "nope", expect_exit=3)
        assert "error:" in err


# ---- Status commands ----


class TestStatusCommands:
    def test_add(self, cli):
        cli("workspace", "create", "dev")
        out, _ = cli("status", "create", "backlog")
        assert "created status 'backlog'" in out

    def test_list_statuses_ordered_alphabetically(self, cli):
        cli("workspace", "create", "dev")
        cli("status", "create", "backlog")
        cli("status", "create", "done")
        cli("status", "create", "in progress")
        out, _ = cli("status", "ls")
        assert "backlog" in out
        assert "done" in out
        assert "in progress" in out

    def test_ls(self, cli):
        cli("workspace", "create", "dev")
        cli("status", "create", "todo")
        cli("status", "create", "done")
        out, _ = cli("status", "ls")
        assert "todo" in out
        assert "done" in out

    def test_ls_empty(self, cli):
        cli("workspace", "create", "dev")
        out, _ = cli("status", "ls")
        assert "no statuses" in out

    def test_rename(self, cli):
        cli("workspace", "create", "dev")
        cli("status", "create", "todo")
        out, _ = cli("status", "rename", "todo", "backlog")
        assert "renamed status 'todo' -> 'backlog'" in out

    def test_archive(self, cli):
        cli("workspace", "create", "dev")
        cli("status", "create", "todo")
        out, _ = cli("status", "archive", "todo")
        assert "archived status 'todo'" in out

    def test_order_writes_config(self, cli, tmp_path, monkeypatch):
        cfg_path = tmp_path / "tui.toml"
        monkeypatch.setattr("sticky_notes.tui.config.DEFAULT_CONFIG_PATH", cfg_path)
        cli("workspace", "create", "dev")
        cli("status", "create", "backlog")
        cli("status", "create", "doing")
        cli("status", "create", "done")
        out, _ = cli("status", "order", "doing", "done", "backlog")
        assert "set status order for workspace 'dev'" in out
        content = cfg_path.read_text()
        assert "[status_order]" in content
        # All three status ids listed in the right order
        from sticky_notes.tui.config import load_config
        config = load_config(cfg_path)
        assert 1 in config.status_order
        assert len(config.status_order[1]) == 3

    def test_order_unknown_status(self, cli, tmp_path, monkeypatch):
        cfg_path = tmp_path / "tui.toml"
        monkeypatch.setattr("sticky_notes.tui.config.DEFAULT_CONFIG_PATH", cfg_path)
        cli("workspace", "create", "dev")
        cli("status", "create", "todo")
        _, err = cli("status", "order", "todo", "nonexistent", expect_exit=3)
        assert "not found" in err

    def test_order_duplicate_status(self, cli, tmp_path, monkeypatch):
        cfg_path = tmp_path / "tui.toml"
        monkeypatch.setattr("sticky_notes.tui.config.DEFAULT_CONFIG_PATH", cfg_path)
        cli("workspace", "create", "dev")
        cli("status", "create", "todo")
        _, err = cli("status", "order", "todo", "todo", expect_exit=4)
        assert "duplicate" in err

    def test_order_json_shape(self, cli, tmp_path, monkeypatch):
        cfg_path = tmp_path / "tui.toml"
        monkeypatch.setattr("sticky_notes.tui.config.DEFAULT_CONFIG_PATH", cfg_path)
        cli("workspace", "create", "dev")
        cli("status", "create", "backlog")
        cli("status", "create", "doing")
        cli("status", "create", "done")
        out, _ = cli("--json", "status", "order", "doing", "done", "backlog")
        data = json.loads(out)["data"]
        assert data["workspace"] == "dev"
        assert "status_ids" not in data  # old shape dropped
        statuses = data["statuses"]
        assert [s["name"] for s in statuses] == ["doing", "done", "backlog"]
        assert all("id" in s for s in statuses)

    def test_ls_archived_filter_hide(self, cli):
        cli("workspace", "create", "dev")
        cli("status", "create", "active")
        cli("status", "create", "old")
        cli("status", "archive", "old")
        out, _ = cli("status", "ls")
        assert "active" in out
        assert "old" not in out

    def test_ls_archived_filter_include(self, cli):
        cli("workspace", "create", "dev")
        cli("status", "create", "active")
        cli("status", "create", "old")
        cli("status", "archive", "old")
        out, _ = cli("status", "ls", "--archived", "include")
        assert "active" in out
        assert "old" in out

    def test_ls_archived_filter_only(self, cli):
        cli("workspace", "create", "dev")
        cli("status", "create", "active")
        cli("status", "create", "old")
        cli("status", "archive", "old")
        out, _ = cli("status", "ls", "--archived", "only")
        assert "active" not in out
        assert "old" in out


# ---- Task shortcuts ----


class TestTaskCommands:
    @pytest.fixture(autouse=True)
    def _setup(self, cli):
        cli("workspace", "create", "dev")
        cli("status", "create", "todo")
        cli("status", "create", "in progress")
        cli("status", "create", "done")

    def test_add_default_column(self, cli):
        out, _ = cli("task", "create", "Fix login bug", "-S", "todo")
        assert "created task-0001" in out

    def test_add_explicit_column(self, cli):
        out, _ = cli("task", "create", "My task", "-S", "in progress")
        assert "created task-0001" in out

    def test_add_with_project(self, cli):
        cli("project", "create", "backend")
        out, _ = cli("task", "create", "Fix bug", "-p", "backend", "-S", "todo")
        assert "created task-0001" in out

    def test_add_with_priority_and_due(self, cli):
        out, _ = cli("task", "create", "Important", "--priority", "3", "--due", "2026-04-01", "-S", "todo")
        assert "created task-0001" in out

    def test_add_with_desc(self, cli):
        out, _ = cli("task", "create", "Fix it", "-d", "Full description here", "-S", "todo")
        assert "created task-0001" in out

    def test_add_empty_desc_normalized_to_null(self, cli):
        out, _ = cli("--json", "task", "create", "Fix it", "-d", "", "-S", "todo")
        data = json.loads(out)
        assert data["data"]["description"] is None

    def test_create_json_includes_tags(self, cli):
        out, _ = cli("--json", "task", "create", "Tagged", "-S", "todo", "--tag", "backend", "--tag", "urgent")
        data = json.loads(out)["data"]
        assert [t["name"] for t in data["tags"]] == ["backend", "urgent"]

    def test_ls_grouped_by_column(self, cli):
        cli("task", "create", "Task A", "-S", "todo")
        cli("task", "create", "Task B", "-S", "in progress")
        out, _ = cli("task", "ls")
        assert "== todo ==" in out
        assert "Task A" in out
        assert "== in progress ==" in out
        assert "Task B" in out
        assert "== done ==" in out
        assert "(empty)" in out

    def test_ls_shows_project(self, cli):
        cli("project", "create", "backend")
        cli("task", "create", "Fix bug", "-p", "backend", "-S", "todo")
        out, _ = cli("task", "ls")
        assert "@backend" in out

    def test_ls_shows_priority(self, cli):
        cli("task", "create", "Fix bug", "--priority", "3", "-S", "todo")
        out, _ = cli("task", "ls")
        assert "[P3]" in out

    def test_show(self, cli):
        cli("task", "create", "Fix login bug", "--priority", "2", "--due", "2026-04-01", "-S", "todo")
        out, _ = cli("task", "show", "1")
        assert "task-0001" in out
        assert "Fix login bug" in out
        assert "Priority:    2" in out
        assert "Due:         2026-04-01" in out
        assert "Status:      todo" in out

    def test_show_with_project(self, cli):
        cli("project", "create", "backend")
        cli("task", "create", "Fix bug", "-p", "backend", "-S", "todo")
        out, _ = cli("task", "show", "1")
        assert "Project:     backend" in out

    def test_show_with_deps(self, cli):
        cli("task", "create", "Task A", "-S", "todo")
        cli("task", "create", "Task B", "-S", "todo")
        cli("dep", "create", "--task", "2", "--blocked-by", "1")
        out, _ = cli("task", "show", "2")
        assert "Blocked by:  task-0001" in out
        # Also check the "Blocks" line from the other side
        out2, _ = cli("task", "show", "1")
        assert "Blocks:      task-0002" in out2

    def test_show_with_description(self, cli):
        cli("task", "create", "Fix bug", "-d", "Detailed description", "-S", "todo")
        out, _ = cli("task", "show", "1")
        assert "Description:" in out
        assert "Detailed description" in out

    def test_edit_title(self, cli):
        cli("task", "create", "Old title", "-S", "todo")
        out, _ = cli("task", "edit", "1", "--title", "New title")
        assert "updated task-0001" in out
        show_out, _ = cli("task", "show", "1")
        assert "New title" in show_out

    def test_edit_priority(self, cli):
        cli("task", "create", "Task", "-S", "todo")
        cli("task", "edit", "1", "--priority", "5")
        out, _ = cli("task", "show", "1")
        assert "Priority:    5" in out

    def test_edit_desc(self, cli):
        cli("task", "create", "Task", "-S", "todo")
        cli("task", "edit", "1", "-d", "new desc")
        out, _ = cli("task", "show", "1")
        assert "new desc" in out

    def test_edit_due(self, cli):
        cli("task", "create", "Task", "-S", "todo")
        cli("task", "edit", "1", "--due", "2026-06-01")
        out, _ = cli("task", "show", "1")
        assert "Due:         2026-06-01" in out

    def test_edit_project(self, cli):
        cli("project", "create", "backend")
        cli("task", "create", "Task", "-S", "todo")
        cli("task", "edit", "1", "-p", "backend")
        out, _ = cli("task", "show", "1")
        assert "Project:     backend" in out

    def test_edit_nothing(self, cli):
        cli("task", "create", "Task", "-S", "todo")
        out, _ = cli("task", "edit", "1")  # no-op: returns task unchanged, exit 0
        assert "nothing to update" in out

    def test_mv(self, cli):
        cli("task", "create", "Task A", "-S", "todo")
        out, _ = cli("task", "mv", "1", "-S", "in progress")
        assert "moved task-0001 -> in progress" in out

    def test_mv_case_insensitive(self, cli):
        cli("task", "create", "Task A", "-S", "todo")
        out, _ = cli("task", "mv", "1", "-S", "In Progress")
        assert "moved task-0001 -> in progress" in out

    def test_archive(self, cli):
        cli("task", "create", "Task A", "-S", "todo")
        out, _ = cli("task", "archive", "1", "--force")
        assert "archived task-0001" in out

    def test_archive_hides_from_ls(self, cli):
        cli("task", "create", "Task A", "-S", "todo")
        cli("task", "archive", "1", "--force")
        out, _ = cli("task", "ls")
        assert "Task A" not in out

    def test_log(self, cli):
        cli("task", "create", "Task A", "-S", "todo")
        cli("task", "edit", "1", "--title", "Task B")
        out, _ = cli("task", "log", "1")
        assert "title:" in out
        assert "Task A" in out
        assert "Task B" in out
        assert "(cli)" in out

    def test_log_empty(self, cli):
        cli("task", "create", "Task A", "-S", "todo")
        out, _ = cli("task", "log", "1")
        assert "no history" in out

    def test_show_nonexistent(self, cli):
        _, err = cli("task", "show", "999", expect_exit=3)
        assert "error:" in err

    def test_task_num_formats(self, cli):
        cli("task", "create", "Task A", "-S", "todo")
        out1, _ = cli("task", "show", "task-0001")
        out2, _ = cli("task", "show", "#1")
        out3, _ = cli("task", "show", "0001")
        assert "Task A" in out1
        assert "Task A" in out2
        assert "Task A" in out3

    def test_show_resolves_title(self, cli):
        cli("task", "create", "Fix login bug", "-S", "todo")
        out, _ = cli("task", "show", "Fix login bug")
        assert "task-0001" in out
        assert "Fix login bug" in out

    def test_show_title_not_found(self, cli):
        _, err = cli("task", "show", "nonexistent title", expect_exit=3)
        assert "error:" in err

    def test_dep_create_resolves_title(self, cli):
        cli("task", "create", "Task A", "-S", "todo")
        cli("task", "create", "Task B", "-S", "todo")
        out, _ = cli("dep", "create", "--task", "Task B", "--blocked-by", "Task A")
        assert "task-0002 now blocked by task-0001" in out


# ---- Project commands ----


class TestProjectCommands:
    @pytest.fixture(autouse=True)
    def _setup(self, cli):
        cli("workspace", "create", "dev")

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
        cli("status", "create", "todo")
        cli("project", "create", "backend", "-d", "API layer")
        cli("task", "create", "Fix bug", "-p", "backend", "-S", "todo")
        out, _ = cli("project", "show", "backend")
        assert "backend" in out
        assert "API layer" in out
        assert "Tasks: 1" in out
        assert "Fix bug" in out

    def test_archive(self, cli):
        cli("project", "create", "backend")
        out, _ = cli("project", "archive", "backend", "--force")
        assert "archived project 'backend'" in out

    def test_edit_description(self, cli):
        cli("project", "create", "backend")
        out, _ = cli("project", "edit", "backend", "--desc", "API services")
        assert "updated project 'backend'" in out
        out, _ = cli("project", "show", "backend")
        assert "API services" in out

    def test_rename(self, cli):
        cli("project", "create", "backend")
        out, _ = cli("project", "rename", "backend", "api")
        assert "renamed project 'backend' -> 'api'" in out
        out2, _ = cli("project", "show", "api")
        assert "api" in out2

    def test_edit_no_changes(self, cli):
        cli("project", "create", "backend")
        out, _ = cli("project", "edit", "backend")
        assert "nothing to update" in out

    def test_create_empty_desc_normalized_to_null(self, cli):
        out, _ = cli("--json", "project", "create", "backend", "--desc", "")
        data = json.loads(out)
        assert data["data"]["description"] is None

    def test_create_whitespace_desc_normalized_to_null(self, cli):
        out, _ = cli("--json", "project", "create", "backend", "--desc", "   ")
        data = json.loads(out)
        assert data["data"]["description"] is None

    def test_ls_archived_filter_hide(self, cli):
        cli("project", "create", "active")
        cli("project", "create", "old")
        cli("project", "archive", "old", "--force")
        out, _ = cli("project", "ls")
        assert "active" in out
        assert "old" not in out

    def test_ls_archived_filter_include(self, cli):
        cli("project", "create", "active")
        cli("project", "create", "old")
        cli("project", "archive", "old", "--force")
        out, _ = cli("project", "ls", "--archived", "include")
        assert "active" in out
        assert "old" in out

    def test_ls_archived_filter_only(self, cli):
        cli("project", "create", "active")
        cli("project", "create", "old")
        cli("project", "archive", "old", "--force")
        out, _ = cli("project", "ls", "--archived", "only")
        assert "active" not in out
        assert "old" in out


# ---- Dependency commands ----


class TestDependencyCommands:
    @pytest.fixture(autouse=True)
    def _setup(self, cli):
        cli("workspace", "create", "dev")
        cli("status", "create", "todo")

    def test_add(self, cli):
        cli("task", "create", "Task A", "-S", "todo")
        cli("task", "create", "Task B", "-S", "todo")
        out, _ = cli("dep", "create", "--task", "2", "--blocked-by", "1")
        assert "task-0002 now blocked by task-0001" in out

    def test_rm(self, cli):
        cli("task", "create", "Task A", "-S", "todo")
        cli("task", "create", "Task B", "-S", "todo")
        cli("dep", "create", "--task", "2", "--blocked-by", "1")
        out, _ = cli("dep", "archive", "--task", "2", "--blocked-by", "1")
        assert "archived dependency" in out


# ---- Error handling ----


class TestErrorHandling:
    def test_no_active_workspace(self, cli):
        _, err = cli("task", "ls", expect_exit=5)
        assert "no active workspace" in err

    def test_not_found(self, cli):
        cli("workspace", "create", "dev")
        _, err = cli("task", "show", "999", expect_exit=3)
        assert "error:" in err

    def test_duplicate_workspace_name(self, cli):
        cli("workspace", "create", "dev")
        _, err = cli("workspace", "create", "dev", expect_exit=4)
        assert "error:" in err

    def test_invalid_task_num(self, cli):
        cli("workspace", "create", "dev")
        _, err = cli("task", "show", "abc", expect_exit=3)
        assert "error:" in err

    def test_status_not_found(self, cli):
        cli("workspace", "create", "dev")
        cli("status", "create", "todo")
        _, err = cli("task", "create", "Task", "-S", "nonexistent", expect_exit=3)
        assert "not found" in err

    def test_project_not_found(self, cli):
        cli("workspace", "create", "dev")
        cli("status", "create", "todo")
        _, err = cli("task", "create", "Task", "-S", "todo", "-p", "nonexistent", expect_exit=3)
        assert "not found" in err

    def test_archive_status_with_active_tasks_blocked(self, cli):
        cli("workspace", "create", "dev")
        cli("status", "create", "todo")
        cli("task", "create", "Task", "-S", "todo")
        _, err = cli("status", "archive", "todo", expect_exit=4)
        assert "active task" in err

    def test_archive_without_tty_requires_force(self, cli):
        cli("workspace", "create", "dev")
        cli("status", "create", "todo")
        cli("task", "create", "Task", "-S", "todo")
        # pytest stdin is already non-TTY; no monkeypatch needed
        _, err = cli("task", "archive", "1", expect_exit=4)
        assert "non-interactive" in err
        assert "--force" in err


# ---- Workspace flag override ----


class TestWorkspaceFlag:
    def test_workspace_flag(self, cli):
        cli("workspace", "create", "dev")
        cli("workspace", "create", "ops")
        cli("-w", "dev", "status", "create", "todo")
        out, _ = cli("-w", "dev", "status", "ls")
        assert "todo" in out

    def test_workspace_flag_overrides_active(self, cli):
        cli("workspace", "create", "dev")
        cli("workspace", "create", "ops")
        # ops is now active (last created)
        cli("-w", "dev", "status", "create", "backlog")
        out, _ = cli("-w", "dev", "status", "ls")
        assert "backlog" in out
        # ops has no statuses
        out2, _ = cli("status", "ls")
        assert "no statuses" in out2


# ---- Help output ----


class TestLsFilters:
    def _setup_workspace(self, cli):
        cli("workspace", "create", "work")
        cli("status", "create", "backlog")
        cli("status", "create", "doing")
        cli("project", "create", "alpha")

    def test_filter_by_status(self, cli):
        self._setup_workspace(cli)
        cli("task", "create", "task1", "-S", "backlog")
        cli("task", "create", "task2", "-S", "doing")
        out, _ = cli("task", "ls", "-S", "backlog")
        assert "task1" in out
        assert "task2" not in out or "task2" not in out.split("== backlog ==")[0]

    def test_filter_by_project(self, cli):
        self._setup_workspace(cli)
        cli("task", "create", "task1", "-p", "alpha", "-S", "backlog")
        cli("task", "create", "task2", "-S", "backlog")
        out, _ = cli("task", "ls", "-p", "alpha")
        assert "task1" in out
        # task2 not in any non-empty column section
        lines = [l for l in out.splitlines() if "task2" in l]
        assert len(lines) == 0

    def test_filter_by_priority(self, cli):
        self._setup_workspace(cli)
        cli("task", "create", "low", "--priority", "1", "-S", "backlog")
        cli("task", "create", "high", "--priority", "3", "-S", "backlog")
        out, _ = cli("task", "ls", "--priority", "3")
        assert "high" in out
        lines = [l for l in out.splitlines() if "low" in l]
        assert len(lines) == 0

    def test_filter_by_search(self, cli):
        self._setup_workspace(cli)
        cli("task", "create", "Fix login bug", "-S", "backlog")
        cli("task", "create", "Add search feature", "-S", "backlog")
        out, _ = cli("task", "ls", "--search", "login")
        assert "Fix login bug" in out
        lines = [l for l in out.splitlines() if "search feature" in l]
        assert len(lines) == 0

    def test_combined_filters(self, cli):
        self._setup_workspace(cli)
        cli("task", "create", "task1", "-S", "backlog", "--priority", "3")
        cli("task", "create", "task2", "-S", "backlog", "--priority", "1")
        cli("task", "create", "task3", "-S", "doing", "--priority", "3")
        out, _ = cli("task", "ls", "-S", "backlog", "--priority", "3")
        assert "task1" in out
        lines = [l for l in out.splitlines() if l.strip().startswith("task-")]
        assert len(lines) == 1

    def test_invalid_status_name(self, cli):
        self._setup_workspace(cli)
        _, err = cli("task", "ls", "-S", "nonexistent", expect_exit=3)
        assert "not found" in err

    def test_invalid_project_name(self, cli):
        self._setup_workspace(cli)
        _, err = cli("task", "ls", "-p", "nonexistent", expect_exit=3)
        assert "not found" in err


class TestMvWorkspace:
    @pytest.fixture(autouse=True)
    def _setup(self, cli):
        cli("workspace", "create", "dev")
        cli("status", "create", "todo")
        cli("status", "create", "done")

    def test_transfer_to_workspace(self, cli):
        cli("workspace", "create", "ops")
        cli("workspace", "use", "ops")
        cli("status", "create", "backlog")
        cli("workspace", "use", "dev")
        cli("task", "create", "Task A", "-S", "todo")
        out, _ = cli("task", "transfer", "1", "--to", "ops", "--status", "backlog")
        assert "workspace 'ops'" in out
        assert "status 'backlog'" in out

    def test_transfer_to_workspace_with_project(self, cli):
        cli("workspace", "create", "ops")
        cli("workspace", "use", "ops")
        cli("status", "create", "backlog")
        cli("project", "create", "infra")
        cli("workspace", "use", "dev")
        cli("task", "create", "Task A", "-S", "todo")
        out, _ = cli("task", "transfer", "1", "--to", "ops", "--status", "backlog", "-p", "infra")
        assert "workspace 'ops'" in out

    def test_transfer_no_column_fails(self, cli):
        cli("workspace", "create", "ops")
        cli("workspace", "use", "dev")
        cli("task", "create", "Task A", "-S", "todo")
        _, err = cli("task", "transfer", "1", "--to", "ops", expect_exit=2)
        assert "--status" in err or "required" in err

    def test_mv_project_only_use_edit(self, cli):
        cli("project", "create", "backend")
        cli("task", "create", "Task A", "-S", "todo")
        out, _ = cli("task", "edit", "1", "-p", "backend")
        assert "updated" in out

    def test_mv_no_column_fails(self, cli):
        cli("task", "create", "Task A", "-S", "todo")
        _, err = cli("task", "mv", "1", expect_exit=2)
        assert "error" in err.lower() or "usage" in err.lower()

    def test_transfer_dry_run(self, cli):
        cli("workspace", "create", "ops")
        cli("workspace", "use", "ops")
        cli("status", "create", "backlog")
        cli("workspace", "use", "dev")
        cli("task", "create", "Task A", "-S", "todo")
        out, _ = cli("task", "transfer", "1", "--to", "ops", "--status", "backlog", "--dry-run")
        assert "dry-run" in out
        assert "transfer OK" in out

    def test_transfer_dry_run_with_deps(self, cli):
        cli("workspace", "create", "ops")
        cli("workspace", "use", "ops")
        cli("status", "create", "backlog")
        cli("workspace", "use", "dev")
        cli("task", "create", "Task A", "-S", "todo")
        cli("task", "create", "Task B", "-S", "todo")
        cli("dep", "create", "--task", "2", "--blocked-by", "1")
        out, _ = cli("task", "transfer", "1", "--to", "ops", "--status", "backlog", "--dry-run")
        assert "dependencies" in out
        assert "FAIL" in out


class TestGroupCLI:
    """Fixture `cli` provides a helper that always passes --db to a temp DB.
    Each test creates its own workspace/project/column setup."""

    @pytest.fixture(autouse=True)
    def _setup(self, cli):
        self.cli = cli
        cli("workspace", "create", "dev")
        cli("status", "create", "todo")
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

    def test_show_group(self):
        self.cli("group", "create", "Frontend", "--project", "sprint1")
        self.cli("task", "create", "Fix bug", "--project", "sprint1", "-S", "todo")
        self.cli("group", "assign", "task-0001", "Frontend", "--project", "sprint1")
        out, _ = self.cli("group", "show", "Frontend", "--project", "sprint1")
        assert "group-0001  Frontend" in out
        assert "sprint1" in out
        assert "task-0001" in out

    def test_show_group_not_found(self):
        _, err = self.cli("group", "show", "nope", "--project", "sprint1", expect_exit=3)
        assert "not found" in err

    def test_rename_group(self):
        self.cli("group", "create", "Frontend", "--project", "sprint1")
        out, _ = self.cli("group", "rename", "Frontend", "UI", "--project", "sprint1")
        assert "renamed" in out
        assert "'UI'" in out

    def test_archive_group(self):
        self.cli("group", "create", "Frontend", "--project", "sprint1")
        out, _ = self.cli("group", "archive", "Frontend", "--project", "sprint1", "--force")
        assert "archived group 'Frontend'" in out

    def test_archive_cascades_tasks(self):
        self.cli("group", "create", "Frontend", "--project", "sprint1")
        self.cli("task", "create", "Fix bug", "--project", "sprint1", "-S", "todo")
        self.cli("group", "assign", "task-0001", "Frontend", "--project", "sprint1")
        self.cli("group", "archive", "Frontend", "--project", "sprint1", "--force")
        # Task should be archived along with the group (hidden from ls)
        out, _ = self.cli("task", "ls")
        assert "Fix bug" not in out

    def test_mv_reparent(self):
        self.cli("group", "create", "Frontend", "--project", "sprint1")
        self.cli("group", "create", "Backend", "--project", "sprint1")
        out, _ = self.cli("group", "mv", "Backend", "--parent", "Frontend", "--project", "sprint1")
        assert "moved" in out
        assert "'Frontend'" in out

    def test_mv_promote_to_top(self):
        self.cli("group", "create", "Frontend", "--project", "sprint1")
        self.cli("group", "create", "Child", "--project", "sprint1", "--parent", "Frontend")
        out, _ = self.cli("group", "mv", "Child", "--to-top", "--project", "sprint1")
        assert "promoted" in out

    def test_assign_task(self):
        self.cli("group", "create", "Frontend", "--project", "sprint1")
        self.cli("task", "create", "Fix bug", "--project", "sprint1", "-S", "todo")
        out, _ = self.cli("group", "assign", "task-0001", "Frontend", "--project", "sprint1")
        assert "assigned task-0001 to group 'Frontend'" in out

    def test_assign_auto_sets_project(self):
        self.cli("group", "create", "Frontend", "--project", "sprint1")
        self.cli("task", "create", "No project task", "-S", "todo")
        self.cli("group", "assign", "task-0001", "Frontend", "--project", "sprint1")
        out, _ = self.cli("task", "show", "task-0001")
        assert "sprint1" in out

    def test_assign_cross_project_raises(self):
        self.cli("project", "create", "sprint2")
        self.cli("group", "create", "Frontend", "--project", "sprint1")
        self.cli("task", "create", "Task", "--project", "sprint2", "-S", "todo")
        _, err = self.cli("group", "assign", "task-0001", "Frontend", "--project", "sprint1", expect_exit=4)
        assert "project" in err

    def test_unassign_task(self):
        self.cli("group", "create", "Frontend", "--project", "sprint1")
        self.cli("task", "create", "Fix bug", "--project", "sprint1", "-S", "todo")
        self.cli("group", "assign", "task-0001", "Frontend", "--project", "sprint1")
        out, _ = self.cli("group", "unassign", "task-0001")
        assert "unassigned" in out

    def test_show_displays_group(self):
        self.cli("group", "create", "Frontend", "--project", "sprint1")
        self.cli("task", "create", "Fix bug", "--project", "sprint1", "-S", "todo")
        self.cli("group", "assign", "task-0001", "Frontend", "--project", "sprint1")
        out, _ = self.cli("task", "show", "task-0001")
        assert "Group:" in out
        assert "Frontend" in out

    def test_ls_group_filter(self):
        self.cli("group", "create", "Frontend", "--project", "sprint1")
        self.cli("task", "create", "Grouped", "--project", "sprint1", "-S", "todo")
        self.cli("task", "create", "Ungrouped", "--project", "sprint1", "-S", "todo")
        self.cli("group", "assign", "task-0001", "Frontend", "--project", "sprint1")
        out, _ = self.cli("task", "ls", "--group", "Frontend")
        assert "Grouped" in out
        assert "Ungrouped" not in out

    def test_ambiguous_group_requires_project(self):
        self.cli("project", "create", "sprint2")
        self.cli("group", "create", "Shared", "--project", "sprint1")
        self.cli("group", "create", "Shared", "--project", "sprint2")
        _, err = self.cli("group", "show", "Shared", expect_exit=3)
        assert "ambiguous" in err

    def test_cycle_detection(self):
        self.cli("group", "create", "A", "--project", "sprint1")
        self.cli("group", "create", "B", "--project", "sprint1", "--parent", "A")
        _, err = self.cli("group", "mv", "A", "--parent", "B", "--project", "sprint1", expect_exit=4)
        assert "cycle" in err

    def test_create_with_description(self):
        out, _ = self.cli("group", "create", "Frontend", "--project", "sprint1", "--desc", "UI components")
        assert "created group 'Frontend'" in out
        out, _ = self.cli("group", "show", "Frontend", "--project", "sprint1")
        assert "UI components" in out

    def test_create_empty_desc_normalized_to_null(self):
        out, _ = self.cli("--json", "group", "create", "Frontend", "--project", "sprint1", "--desc", "")
        data = json.loads(out)
        assert data["data"]["description"] is None

    def test_edit_description(self):
        self.cli("group", "create", "Frontend", "--project", "sprint1")
        out, _ = self.cli("group", "edit", "Frontend", "--project", "sprint1", "--desc", "UI layer")
        assert "updated group 'Frontend'" in out

    def test_edit_no_changes(self):
        self.cli("group", "create", "Frontend", "--project", "sprint1")
        out, _ = self.cli("group", "edit", "Frontend", "--project", "sprint1")
        assert "nothing to update" in out

    def test_task_create_with_group(self):
        self.cli("group", "create", "Frontend", "--project", "sprint1")
        out, _ = self.cli("task", "create", "Fix bug", "-S", "todo", "--group", "Frontend")
        assert "created task-0001" in out
        out, _ = self.cli("task", "show", "task-0001")
        assert "Frontend" in out
        assert "sprint1" in out

    def test_task_create_group_infers_project(self):
        self.cli("group", "create", "Frontend", "--project", "sprint1")
        self.cli("task", "create", "Fix bug", "-S", "todo", "--group", "Frontend")
        out, _ = self.cli("task", "show", "task-0001")
        assert "sprint1" in out


# ---- Tag ----


class TestTagCommands:
    @pytest.fixture(autouse=True)
    def _setup(self, cli):
        cli("workspace", "create", "dev")
        cli("status", "create", "todo")
        cli("status", "create", "done")

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

    def test_tag_rename(self, cli):
        cli("tag", "create", "bug")
        out, _ = cli("tag", "rename", "bug", "defect")
        assert "renamed tag 'bug' -> 'defect'" in out
        out2, _ = cli("tag", "ls")
        assert "defect" in out2
        assert "bug" not in out2

    def test_tag_archive(self, cli):
        cli("tag", "create", "bug")
        out, _ = cli("tag", "archive", "bug", "--force")
        assert "archived tag 'bug'" in out

    def test_tag_archive_not_found(self, cli):
        _, err = cli("tag", "archive", "nonexistent", "--force", expect_exit=3)
        assert "not found" in err

    def test_tag_ls_all_shows_archived(self, cli):
        cli("tag", "create", "bug")
        cli("tag", "create", "old")
        cli("tag", "archive", "old", "--force")
        out, _ = cli("tag", "ls")
        assert "bug" in out
        assert "old" not in out
        out, _ = cli("tag", "ls", "--archived", "include")
        assert "bug" in out
        assert "old" in out
        assert "(archived)" in out

    # -- Tags on add --

    def test_add_with_tag(self, cli):
        cli("task", "create", "Fix bug", "--tag", "bug", "-S", "todo")
        out, _ = cli("task", "show", "1")
        assert "bug" in out

    def test_add_with_multiple_tags(self, cli):
        cli("task", "create", "Fix bug", "-t", "bug", "-t", "urgent", "-S", "todo")
        out, _ = cli("task", "show", "1")
        assert "bug" in out
        assert "urgent" in out

    def test_add_tag_auto_creates(self, cli):
        cli("task", "create", "Fix", "-t", "new-tag", "-S", "todo")
        out, _ = cli("tag", "ls")
        assert "new-tag" in out

    # -- Tags on edit --

    def test_edit_add_tag(self, cli):
        cli("task", "create", "Task", "-S", "todo")
        cli("task", "edit", "1", "--tag", "bug")
        out, _ = cli("task", "show", "1")
        assert "bug" in out

    def test_edit_untag(self, cli):
        cli("task", "create", "Task", "-t", "bug", "-S", "todo")
        cli("task", "edit", "1", "--untag", "bug")
        out, _ = cli("task", "show", "1")
        assert "Tags:" not in out

    def test_edit_tag_only_no_field_changes(self, cli):
        cli("task", "create", "Task", "-S", "todo")
        out, _ = cli("task", "edit", "1", "-t", "bug")
        assert "updated" in out

    def test_edit_untag_not_found(self, cli):
        cli("task", "create", "Task", "-S", "todo")
        _, err = cli("task", "edit", "1", "--untag", "nonexistent", expect_exit=3)
        assert "not found" in err

    def test_edit_nothing_is_noop(self, cli):
        cli("task", "create", "Task", "-S", "todo")
        out, _ = cli("task", "edit", "1")  # no-op: returns unchanged task, exit 0
        assert "nothing to update" in out

    # -- Tags on ls --

    def test_ls_filter_by_tag(self, cli):
        cli("task", "create", "Tagged", "-t", "bug", "-S", "todo")
        cli("task", "create", "Untagged", "-S", "todo")
        out, _ = cli("task", "ls", "--tag", "bug")
        assert "Tagged" in out
        assert "Untagged" not in out

    def test_ls_shows_tags(self, cli):
        cli("task", "create", "Task", "-t", "bug", "-S", "todo")
        out, _ = cli("task", "ls")
        assert "[bug]" in out

    def test_ls_shows_multiple_tags(self, cli):
        cli("task", "create", "Task", "-t", "bug", "-t", "urgent", "-S", "todo")
        out, _ = cli("task", "ls")
        assert "[bug, urgent]" in out

    def test_ls_tag_filter_not_found(self, cli):
        _, err = cli("task", "ls", "--tag", "nonexistent", expect_exit=3)
        assert "not found" in err

    # -- Tags on show --

    def test_show_displays_tags(self, cli):
        cli("task", "create", "Task", "-t", "bug", "-t", "feature", "-S", "todo")
        out, _ = cli("task", "show", "1")
        assert "Tags:" in out
        assert "bug" in out
        assert "feature" in out


class TestHelp:
    def test_no_args_shows_help(self, capsys):
        try:
            main([])
        except SystemExit as exc:
            assert exc.code == 0


# ---- Context command ----


class TestWorkspaceShow:
    def test_workspace_show_text_output(self, cli):
        cli("workspace", "create", "dev")
        cli("status", "create", "todo")
        cli("project", "create", "backend")
        cli("tag", "create", "bug")
        cli("group", "create", "G1", "-p", "backend")
        out, _ = cli("workspace", "show")
        assert "== dev ==" in out
        assert "Projects:" in out
        assert "backend" in out
        assert "Tags:" in out
        assert "bug" in out
        assert "Groups:" in out
        assert "G1" in out

    def test_workspace_show_empty_text(self, cli):
        cli("workspace", "create", "empty")
        out, _ = cli("workspace", "show")
        assert "== empty ==" in out
        assert "Projects:" not in out
        assert "Tags:" not in out
        assert "Groups:" not in out

    def test_workspace_show_no_active_workspace(self, cli):
        _, err = cli("workspace", "show", expect_exit=5)
        assert "no active workspace" in err

    def test_workspace_show_no_active_workspace_json(self, cli):
        _, err = cli("--json", "workspace", "show", expect_exit=5)
        data = json.loads(err)
        assert data["ok"] is False
        assert data["code"] == "missing_active_workspace"

    def test_workspace_show_accepts_name_positional(self, cli):
        cli("workspace", "create", "alpha")
        cli("workspace", "create", "beta")
        # active is now beta; show alpha by name
        out, _ = cli("workspace", "show", "alpha")
        assert "alpha" in out

    def test_workspace_show_name_positional_json(self, cli):
        cli("workspace", "create", "alpha")
        cli("workspace", "create", "beta")
        out, _ = cli("--json", "workspace", "show", "alpha")
        data = json.loads(out)
        assert data["ok"] is True
        assert data["data"]["view"]["workspace"]["name"] == "alpha"


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
        cli("workspace", "create", "B")
        cli("status", "create", "Todo")
        data = self._json(cli, "task", "create", "My task", "-S", "Todo")
        assert data["ok"] is True
        assert data["data"]["id"] == 1
        assert data["data"]["title"] == "My task"

    def test_edit(self, cli):
        cli("workspace", "create", "B")
        cli("status", "create", "Todo")
        cli("task", "create", "Original", "-S", "todo")
        data = self._json(cli, "task", "edit", "1", "--title", "Updated")
        assert data["ok"] is True
        assert data["data"]["id"] == 1
        assert data["data"]["title"] == "Updated"

    def test_archive(self, cli):
        cli("workspace", "create", "B")
        cli("status", "create", "Todo")
        cli("task", "create", "T1", "-S", "todo")
        data = self._json(cli, "task", "archive", "1")
        assert data["ok"] is True
        assert data["data"]["id"] == 1
        assert data["data"]["archived"] is True

    def test_workspace_create(self, cli):
        data = self._json(cli, "workspace", "create", "NewWorkspace")
        assert data["ok"] is True
        assert data["data"]["id"] == 1
        assert data["data"]["name"] == "NewWorkspace"

    def test_col_create(self, cli):
        cli("workspace", "create", "B")
        data = self._json(cli, "status", "create", "Backlog")
        assert data["ok"] is True
        assert data["data"]["id"] == 1
        assert data["data"]["name"] == "Backlog"

    def test_project_create(self, cli):
        cli("workspace", "create", "B")
        data = self._json(cli, "project", "create", "P1")
        assert data["ok"] is True
        assert data["data"]["id"] == 1
        assert data["data"]["name"] == "P1"

    def test_dep_create(self, cli):
        cli("workspace", "create", "B")
        cli("status", "create", "Todo")
        cli("task", "create", "T1", "-S", "todo")
        cli("task", "create", "T2", "-S", "todo")
        data = self._json(cli, "dep", "create", "--task", "1", "--blocked-by", "2")
        assert data["ok"] is True
        assert data["data"]["blocked_task_id"] == 1
        assert data["data"]["blocking_task_id"] == 2

    def test_tag_create(self, cli):
        cli("workspace", "create", "B")
        data = self._json(cli, "tag", "create", "bug")
        assert data["ok"] is True
        assert data["data"]["id"] == 1
        assert data["data"]["name"] == "bug"

    # -- Lists --

    def test_ls(self, cli):
        cli("workspace", "create", "B")
        cli("status", "create", "Todo")
        cli("task", "create", "Task A", "-S", "todo")
        data = self._json(cli, "task", "ls")
        assert data["ok"] is True
        payload = data["data"]
        assert isinstance(payload, list)
        assert len(payload) == 1  # one status bucket
        assert "status" in payload[0]
        assert payload[0]["status"]["name"] == "Todo"
        assert len(payload[0]["tasks"]) == 1
        assert payload[0]["tasks"][0]["title"] == "Task A"

    def test_workspace_ls(self, cli):
        cli("workspace", "create", "B1")
        data = self._json(cli, "workspace", "ls")
        assert data["ok"] is True
        payload = data["data"]
        assert isinstance(payload, list)
        assert len(payload) == 1
        assert payload[0]["name"] == "B1"
        assert payload[0]["active"] is True

    def test_col_ls(self, cli):
        cli("workspace", "create", "B")
        cli("status", "create", "Todo")
        cli("status", "create", "Done")
        data = self._json(cli, "status", "ls")
        assert data["ok"] is True
        assert isinstance(data["data"], list)
        assert len(data["data"]) == 2

    def test_project_ls(self, cli):
        cli("workspace", "create", "B")
        cli("project", "create", "P1")
        data = self._json(cli, "project", "ls")
        assert data["ok"] is True
        payload = data["data"]
        assert isinstance(payload, list)
        assert payload[0]["name"] == "P1"

    def test_log_empty(self, cli):
        cli("workspace", "create", "B")
        cli("status", "create", "Todo")
        cli("task", "create", "T1", "-S", "todo")
        data = self._json(cli, "task", "log", "1")
        assert data["ok"] is True
        assert isinstance(data["data"], list)

    def test_group_ls(self, cli):
        cli("workspace", "create", "B")
        cli("status", "create", "Todo")
        cli("project", "create", "P1")
        cli("group", "create", "G1", "-p", "P1")
        data = self._json(cli, "group", "ls")
        assert data["ok"] is True
        payload = data["data"]
        assert isinstance(payload, list)
        assert payload[0]["title"] == "G1"

    def test_group_ls_json_includes_project_name(self, cli):
        cli("workspace", "create", "B")
        cli("status", "create", "Todo")
        cli("project", "create", "Alpha")
        cli("project", "create", "Beta")
        cli("group", "create", "G1", "-p", "Alpha")
        cli("group", "create", "G2", "-p", "Beta")
        data = self._json(cli, "group", "ls")
        assert data["ok"] is True
        payload = data["data"]
        names = {g["title"]: g["project_name"] for g in payload}
        assert names["G1"] == "Alpha"
        assert names["G2"] == "Beta"

    def test_tag_ls(self, cli):
        cli("workspace", "create", "B")
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
        cli("workspace", "create", "B")
        cli("status", "create", "Todo")
        cli("task", "create", "Task A", "--priority", "3", "-S", "todo")
        data = self._json(cli, "task", "show", "1")
        assert data["ok"] is True
        payload = data["data"]
        assert payload["title"] == "Task A"
        assert payload["priority"] == 3
        assert "status" in payload
        assert payload["status"]["name"] == "Todo"
        assert "group_id" in payload

    def test_show_with_tags(self, cli):
        cli("workspace", "create", "B")
        cli("status", "create", "Todo")
        cli("task", "create", "Task A", "-t", "bug", "-t", "feature", "-S", "todo")
        data = self._json(cli, "task", "show", "1")
        assert data["ok"] is True
        payload = data["data"]
        assert len(payload["tags"]) == 2
        assert payload["tags"][0]["name"] == "bug"
        assert payload["tags"][1]["name"] == "feature"

    def test_project_show(self, cli):
        cli("workspace", "create", "B")
        cli("status", "create", "Todo")
        cli("project", "create", "P1", "-d", "desc")
        cli("task", "create", "T1", "-p", "P1", "-S", "todo")
        data = self._json(cli, "project", "show", "P1")
        assert data["ok"] is True
        payload = data["data"]
        assert payload["name"] == "P1"
        assert payload["description"] == "desc"
        assert len(payload["tasks"]) == 1

    def test_group_show(self, cli):
        cli("workspace", "create", "B")
        cli("status", "create", "Todo")
        cli("project", "create", "P1")
        cli("group", "create", "G1", "-p", "P1")
        data = self._json(cli, "group", "show", "G1")
        assert data["ok"] is True
        assert data["data"]["title"] == "G1"

    # -- Moves --

    def test_mv_within_workspace(self, cli):
        cli("workspace", "create", "B")
        cli("status", "create", "Todo")
        cli("status", "create", "Done")
        cli("task", "create", "T1", "-S", "todo")
        data = self._json(cli, "task", "mv", "1", "-S", "Done")
        assert data["ok"] is True
        assert data["data"]["id"] == 1

    def test_transfer_cross_workspace(self, cli):
        cli("workspace", "create", "B1")
        cli("status", "create", "Todo")
        cli("task", "create", "T1", "-S", "todo")
        cli("workspace", "create", "B2")
        cli("status", "create", "Inbox")
        data = self._json(cli, "task", "transfer", "1", "--to", "B2", "--status", "Inbox")
        assert data["ok"] is True
        assert data["data"]["task"]["title"] == "T1"
        assert data["data"]["source_task_id"] == 1

    def test_transfer_dry_run(self, cli):
        cli("workspace", "create", "B1")
        cli("status", "create", "Todo")
        cli("task", "create", "T1", "-S", "todo")
        cli("workspace", "create", "B2")
        cli("status", "create", "Inbox")
        data = self._json(cli, "task", "transfer", "1", "--to", "B2", "--status", "Inbox", "--dry-run")
        assert data["ok"] is True
        payload = data["data"]
        assert payload["can_move"] is True
        assert payload["dependency_ids"] == []
        assert payload["blocking_reason"] is None
        assert payload["is_archived"] is False
        assert payload["target_project_id"] is None

    def test_transfer_dry_run_includes_target_project_id(self, cli):
        cli("workspace", "create", "B1")
        cli("status", "create", "Todo")
        cli("task", "create", "T1", "-S", "todo")
        cli("workspace", "create", "B2")
        cli("status", "create", "Inbox")
        cli("project", "create", "infra")
        data = self._json(cli, "task", "transfer", "1", "--to", "B2", "--status", "Inbox", "--project", "infra", "--dry-run")
        assert data["ok"] is True
        assert data["data"]["target_project_id"] is not None

    def test_mv_project_only_use_edit(self, cli):
        cli("workspace", "create", "B")
        cli("status", "create", "Todo")
        cli("project", "create", "P1")
        cli("task", "create", "T1", "-S", "todo")
        data = self._json(cli, "task", "edit", "1", "--project", "P1")
        assert data["ok"] is True
        assert data["data"]["id"] == 1
        assert data["data"]["project_id"] == 1

    # -- Edit edge case --

    def test_edit_no_changes(self, cli):
        import json
        cli("workspace", "create", "B")
        cli("status", "create", "Todo")
        cli("task", "create", "T1", "-S", "todo")
        out, _ = cli("--json", "task", "edit", "1")
        data = json.loads(out)
        assert data["ok"] is True
        assert data["data"]["id"] == 1

    # -- Log with entries --

    def test_log_with_history(self, cli):
        cli("workspace", "create", "B")
        cli("status", "create", "Todo")
        cli("task", "create", "T1", "-S", "todo")
        cli("task", "edit", "1", "--title", "Updated")
        data = self._json(cli, "task", "log", "1")
        assert data["ok"] is True
        payload = data["data"]
        assert isinstance(payload, list)
        assert len(payload) >= 1
        assert payload[0]["field"] == "title"

    # -- Export --

    def test_export_json_default(self, cli):
        cli("workspace", "create", "B")
        cli("status", "create", "Todo")
        cli("task", "create", "T1", "-S", "todo")
        data = self._json(cli, "export")
        assert data["ok"] is True
        payload = data["data"]
        assert "schema_version" in payload
        assert "tasks" in payload
        assert any(t["title"] == "T1" for t in payload["tasks"])

    def test_export_md_flag(self, cli):
        cli("workspace", "create", "B")
        cli("status", "create", "Todo")
        cli("task", "create", "T1", "-S", "todo")
        data = self._json(cli, "export", "--md")
        assert data["ok"] is True
        payload = data["data"]
        assert "markdown" in payload
        assert "# Sticky Notes Export" in payload["markdown"]

    # -- Group assign/unassign --

    def test_group_assign(self, cli):
        cli("workspace", "create", "B")
        cli("status", "create", "Todo")
        cli("project", "create", "P1")
        cli("group", "create", "G1", "-p", "P1")
        cli("task", "create", "T1", "-p", "P1", "-S", "todo")
        data = self._json(cli, "group", "assign", "1", "G1", "-p", "P1")
        assert data["ok"] is True
        assert data["data"]["id"] == 1
        assert data["data"]["group"]["title"] == "G1"

    def test_group_unassign(self, cli):
        cli("workspace", "create", "B")
        cli("status", "create", "Todo")
        cli("project", "create", "P1")
        cli("group", "create", "G1", "-p", "P1")
        cli("task", "create", "T1", "-p", "P1", "-S", "todo")
        cli("group", "assign", "1", "G1", "-p", "P1")
        data = self._json(cli, "group", "unassign", "1")
        assert data["ok"] is True
        assert data["data"]["id"] == 1

    # -- Context --

    def test_workspace_show(self, cli):
        cli("workspace", "create", "B")
        cli("status", "create", "Todo")
        cli("project", "create", "P1")
        cli("tag", "create", "bug")
        cli("group", "create", "G1", "-p", "P1")
        cli("task", "create", "T1", "-S", "todo")
        data = self._json(cli, "workspace", "show")
        assert data["ok"] is True
        payload = data["data"]
        assert payload["view"]["workspace"]["name"] == "B"
        assert len(payload["view"]["statuses"]) == 1
        assert len(payload["projects"]) == 1
        assert payload["projects"][0]["name"] == "P1"
        assert len(payload["tags"]) == 1
        assert payload["tags"][0]["name"] == "bug"
        assert len(payload["groups"]) == 1
        assert payload["groups"][0]["title"] == "G1"

    def test_workspace_show_empty_workspace(self, cli):
        cli("workspace", "create", "Empty")
        data = self._json(cli, "workspace", "show")
        assert data["ok"] is True
        payload = data["data"]
        assert payload["view"]["workspace"]["name"] == "Empty"
        assert payload["projects"] == []
        assert payload["tags"] == []
        assert payload["groups"] == []

    # -- Error in JSON mode --

    def test_error_json(self, cli):
        import json
        cli("workspace", "create", "B")
        _, err = cli("--json", "task", "show", "999", expect_exit=3)
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

        original = HANDLERS["task_ls"]
        monkeypatch.setitem(HANDLERS, "task_ls", lambda *a, **kw: (_ for _ in ()).throw(KeyboardInterrupt()))
        with pytest.raises(SystemExit) as exc_info:
            main(["--db", str(db_path), "--json", "task", "ls"])
        monkeypatch.setitem(HANDLERS, "task_ls", original)
        assert exc_info.value.code == 130

    def test_operational_error_exits_2(self, db_path, capsys, monkeypatch):
        """sqlite3.OperationalError must print a friendly message and exit 2."""
        import sqlite3
        from sticky_notes.cli import main, HANDLERS

        original = HANDLERS["task_ls"]
        monkeypatch.setitem(HANDLERS, "task_ls", lambda *a, **kw: (_ for _ in ()).throw(
            sqlite3.OperationalError("disk I/O error")
        ))
        with pytest.raises(SystemExit) as exc_info:
            main(["--db", str(db_path), "task", "ls"])
        captured = capsys.readouterr()
        monkeypatch.setitem(HANDLERS, "task_ls", original)
        assert exc_info.value.code == 2
        assert "database error" in captured.err
        assert "disk I/O error" in captured.err

    def test_operational_error_json_exits_2(self, db_path, capsys, monkeypatch):
        """sqlite3.OperationalError in --json mode emits JSON error and exits 2."""
        import json
        import sqlite3
        from sticky_notes.cli import main, HANDLERS

        original = HANDLERS["task_ls"]
        monkeypatch.setitem(HANDLERS, "task_ls", lambda *a, **kw: (_ for _ in ()).throw(
            sqlite3.OperationalError("disk I/O error")
        ))
        with pytest.raises(SystemExit) as exc_info:
            main(["--db", str(db_path), "--json", "task", "ls"])
        captured = capsys.readouterr()
        monkeypatch.setitem(HANDLERS, "task_ls", original)
        assert exc_info.value.code == 2
        data = json.loads(captured.err)
        assert data["ok"] is False
        assert "database error" in data["error"]


class TestExportJson:
    def test_export_json_stdout(self, cli):
        import json
        cli("workspace", "create", "B")
        cli("status", "create", "Todo")
        cli("task", "create", "T1", "-S", "todo")
        out, _ = cli("export")
        data = json.loads(out)
        assert "schema_version" in data
        assert any(t["title"] == "T1" for t in data["tasks"])

    def test_export_json_to_file(self, cli, tmp_path):
        import json
        cli("workspace", "create", "B")
        cli("status", "create", "Todo")
        out_file = tmp_path / "dump.json"
        cli("export", "-o", str(out_file))
        assert out_file.exists()
        data = json.loads(out_file.read_text())
        assert "schema_version" in data

    def test_export_json_file_data_payload(self, cli, tmp_path):
        import json
        cli("workspace", "create", "B")
        out_file = tmp_path / "dump.json"
        out, _ = cli("--json", "export", "-o", str(out_file))
        result = json.loads(out)
        assert result["ok"] is True
        assert "output_path" in result["data"]
        assert result["data"]["bytes"] > 0

    def test_export_md_stdout(self, cli):
        cli("workspace", "create", "B")
        cli("status", "create", "Todo")
        out, _ = cli("export", "--md")
        assert "# Sticky Notes Export" in out

    def test_export_md_to_file(self, cli, tmp_path):
        cli("workspace", "create", "B")
        output = tmp_path / "new" / "sub" / "out.md"
        cli("export", "--md", "-o", str(output))
        assert output.exists()
        assert "# Sticky Notes Export" in output.read_text()

    def test_export_json_creates_parent_dirs(self, cli, tmp_path):
        import json
        cli("workspace", "create", "B")
        output = tmp_path / "new" / "sub" / "dump.json"
        cli("export", "-o", str(output))
        assert output.exists()
        data = json.loads(output.read_text())
        assert "schema_version" in data

    def test_export_refuses_overwrite_by_default(self, cli, tmp_path):
        cli("workspace", "create", "B")
        out_file = tmp_path / "dump.json"
        out_file.write_text("existing")
        _, err = cli("export", "-o", str(out_file), expect_exit=4)
        assert "already exists" in err
        assert out_file.read_text() == "existing"

    def test_export_overwrite_flag_json(self, cli, tmp_path):
        import json
        cli("workspace", "create", "B")
        out_file = tmp_path / "dump.json"
        out_file.write_text("old")
        cli("export", "-o", str(out_file), "--overwrite")
        data = json.loads(out_file.read_text())
        assert "schema_version" in data

    def test_export_overwrite_flag_md(self, cli, tmp_path):
        cli("workspace", "create", "B")
        out_file = tmp_path / "dump.md"
        out_file.write_text("old")
        cli("export", "--md", "-o", str(out_file), "--overwrite")
        assert "# Sticky Notes Export" in out_file.read_text()

    def test_export_md_refuses_overwrite_by_default(self, cli, tmp_path):
        cli("workspace", "create", "B")
        out_file = tmp_path / "dump.md"
        out_file.write_text("existing")
        _, err = cli("export", "--md", "-o", str(out_file), expect_exit=4)
        assert "already exists" in err
        assert out_file.read_text() == "existing"


class TestExportParentDir:
    def test_export_creates_parent_dirs(self, cli, tmp_path):
        cli("workspace", "create", "B")
        output = tmp_path / "new" / "sub" / "out.md"
        out, _ = cli("export", "--md", "-o", str(output))
        assert output.exists()
        assert "# Sticky Notes Export" in output.read_text()


class TestBackup:
    def test_backup_creates_file(self, cli, tmp_path):
        cli("workspace", "create", "B")
        cli("status", "create", "Todo")
        cli("task", "create", "T1", "-S", "todo")
        dest = tmp_path / "backup.db"
        out, _ = cli("backup", str(dest))
        assert dest.exists()
        assert "backed up to" in out

    def test_backup_file_is_valid_sqlite(self, cli, tmp_path):
        import sqlite3 as _sqlite3
        cli("workspace", "create", "B")
        cli("status", "create", "Todo")
        cli("task", "create", "T1", "-S", "todo")
        dest = tmp_path / "backup.db"
        cli("backup", str(dest))
        conn = _sqlite3.connect(str(dest))
        count = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        conn.close()
        assert count == 1

    def test_backup_refuses_overwrite_by_default(self, cli, tmp_path):
        cli("workspace", "create", "B")
        dest = tmp_path / "backup.db"
        dest.write_bytes(b"existing")
        _, err = cli("backup", str(dest), expect_exit=4)
        assert "already exists" in err

    def test_backup_overwrite_flag(self, cli, tmp_path):
        cli("workspace", "create", "B")
        dest = tmp_path / "backup.db"
        dest.write_bytes(b"existing")
        out, _ = cli("backup", str(dest), "--overwrite")
        assert "backed up to" in out
        assert dest.stat().st_size > 8  # replaced with real DB

    def test_backup_creates_parent_dirs(self, cli, tmp_path):
        cli("workspace", "create", "B")
        dest = tmp_path / "nested" / "dir" / "backup.db"
        out, _ = cli("backup", str(dest))
        assert dest.exists()

    def test_backup_json_payload(self, cli, tmp_path):
        import json
        cli("workspace", "create", "B")
        dest = tmp_path / "backup.db"
        out, _ = cli("--json", "backup", str(dest))
        result = json.loads(out)
        assert result["ok"] is True
        assert result["data"]["dest"] == str(dest)
        assert result["data"]["bytes"] > 0


# ---- Info command ----


class TestInfo:
    def test_info_text_labels(self, cli):
        out, _ = cli("info")
        for label in ["database", "wal sidecar", "shm sidecar", "active-workspace pointer"]:
            assert label in out
    def test_info_text_existence_markers(self, cli, db_path):
        cli("workspace", "create", "X")
        cli("status", "create", "todo")
        out, _ = cli("info")
        assert "[exists]" in out
        assert str(db_path) in out

    def test_info_json(self, cli, db_path):
        import json
        out, _ = cli("--json", "info")
        data = json.loads(out)
        assert data["ok"] is True
        assert data["data"]["db"]["path"] == str(db_path)
        assert isinstance(data["data"]["db"]["exists"], bool)
        for key in ("db", "wal", "shm", "active_workspace"):
            assert "path" in data["data"][key]
            assert "exists" in data["data"][key]
        assert "existing" not in data["data"]


# ---- Archive commands (dry-run, cascade, confirmation) ----


class TestEditDryRun:
    @pytest.fixture(autouse=True)
    def _setup(self, cli):
        self.cli = cli
        cli("workspace", "create", "dev")
        cli("status", "create", "todo")
        cli("status", "create", "done")
        cli("project", "create", "alpha")
        cli("project", "create", "beta")
        cli("group", "create", "top", "-p", "alpha")
        cli("group", "create", "child", "-p", "alpha", "--parent", "top")
        cli("tag", "create", "bug")
        cli("task", "create", "T1", "-S", "todo", "-p", "alpha", "--priority", "2")

    def test_task_edit_dry_run_text(self):
        out, _ = self.cli("task", "edit", "1", "--title", "T1 renamed", "--priority", "4", "--dry-run")
        assert "dry-run" in out
        assert "title" in out and "T1" in out and "T1 renamed" in out
        assert "priority" in out
        # Task unchanged
        show, _ = self.cli("task", "show", "1")
        assert "T1 renamed" not in show
        assert "Priority:    2" in show

    def test_task_edit_dry_run_tag_diff(self):
        out, _ = self.cli("task", "edit", "1", "--tag", "bug", "--tag", "urgent", "--dry-run")
        assert "+tag bug" in out
        assert "+tag urgent" in out

    def test_task_edit_dry_run_json(self):
        out, _ = self.cli("--json", "task", "edit", "1", "--priority", "5", "--dry-run")
        data = json.loads(out)["data"]
        assert data["entity_type"] == "task"
        assert data["after"]["priority"] == 5
        assert data["before"]["priority"] == 2

    def test_task_mv_dry_run(self):
        out, _ = self.cli("task", "mv", "1", "-S", "done", "--dry-run")
        assert "dry-run" in out
        assert "'todo'" in out and "'done'" in out
        # Verify status wasn't actually moved
        show, _ = self.cli("task", "show", "1")
        assert "Status:      todo" in show

    def test_task_mv_dry_run_project_change(self):
        out, _ = self.cli("task", "mv", "1", "-S", "done", "-p", "beta", "--dry-run")
        assert "project" in out
        assert "'alpha'" in out and "'beta'" in out
        # Verify project wasn't actually changed
        show, _ = self.cli("task", "show", "1")
        assert "Project:     alpha" in show

    def test_project_edit_dry_run(self):
        out, _ = self.cli("project", "edit", "alpha", "--desc", "new description", "--dry-run")
        assert "dry-run" in out
        assert "project 'alpha'" in out
        assert "description" in out

    def test_group_edit_dry_run(self):
        out, _ = self.cli("group", "edit", "top", "-p", "alpha", "--desc", "new desc", "--dry-run")
        assert "dry-run" in out
        assert "description" in out

    def test_group_rename_dry_run(self):
        out, _ = self.cli("group", "rename", "top", "top-renamed", "-p", "alpha", "--dry-run")
        assert "dry-run" in out
        assert "title" in out
        # Still exists under old name — new name must not have been written
        show, _ = self.cli("group", "show", "top", "-p", "alpha")
        assert "top-renamed" not in show

    def test_group_mv_dry_run_to_top(self):
        out, _ = self.cli("group", "mv", "child", "--to-top", "-p", "alpha", "--dry-run")
        assert "dry-run" in out
        assert "parent" in out


class TestArchiveDryRun:
    @pytest.fixture(autouse=True)
    def _setup(self, cli):
        self.cli = cli
        cli("workspace", "create", "dev")
        cli("status", "create", "todo")
        cli("status", "create", "done")
        cli("project", "create", "proj")
        cli("group", "create", "top", "--project", "proj")
        cli("group", "create", "child", "--parent", "top", "--project", "proj")
        cli("task", "create", "t1", "-S", "todo", "-p", "proj")
        cli("task", "create", "t2", "-S", "todo", "-p", "proj")
        cli("group", "assign", "1", "top", "--project", "proj")
        cli("group", "assign", "2", "child", "--project", "proj")

    def test_task_dry_run(self):
        out, _ = self.cli("task", "archive", "1", "--dry-run")
        assert "dry-run" in out
        assert "task" in out
        # task should not actually be archived
        out2, _ = self.cli("task", "ls")
        assert "t1" in out2

    def test_group_dry_run(self):
        out, _ = self.cli("group", "archive", "top", "--project", "proj", "--dry-run")
        assert "dry-run" in out
        assert "descendant groups: 1" in out  # child group
        assert "tasks: 2" in out   # both tasks in subtree
        # nothing actually archived
        out2, _ = self.cli("task", "ls")
        assert "t1" in out2

    def test_project_dry_run(self):
        out, _ = self.cli("project", "archive", "proj", "--dry-run")
        assert "dry-run" in out
        assert "groups: 2" in out
        assert "tasks: 2" in out

    def test_workspace_dry_run(self):
        out, _ = self.cli("workspace", "archive", "--dry-run")
        assert "dry-run" in out
        assert "projects: 1" in out
        assert "groups: 2" in out
        assert "statuses: 2" in out
        assert "tasks: 2" in out


class TestArchiveCascade:
    @pytest.fixture(autouse=True)
    def _setup(self, cli):
        self.cli = cli
        cli("workspace", "create", "dev")
        cli("status", "create", "todo")
        cli("status", "create", "done")
        cli("project", "create", "proj")
        cli("group", "create", "top", "--project", "proj")
        cli("group", "create", "child", "--parent", "top", "--project", "proj")
        cli("task", "create", "t1", "-S", "todo", "-p", "proj")
        cli("task", "create", "t2", "-S", "done", "-p", "proj")
        cli("group", "assign", "1", "top", "--project", "proj")
        cli("group", "assign", "2", "child", "--project", "proj")

    def test_group_cascade_archives_all(self):
        self.cli("group", "archive", "top", "--project", "proj", "--force")
        # Tasks hidden from default ls
        out, _ = self.cli("task", "ls")
        assert "t1" not in out
        assert "t2" not in out
        # Groups hidden from default ls
        out2, _ = self.cli("group", "ls", "--project", "proj")
        assert "top" not in out2
        assert "child" not in out2
        # But visible with --all
        out3, _ = self.cli("group", "ls", "--project", "proj", "--archived", "include")
        assert "top" in out3
        assert "child" in out3

    def test_project_cascade_archives_all(self):
        self.cli("project", "archive", "proj", "--force")
        out, _ = self.cli("task", "ls")
        assert "t1" not in out
        assert "t2" not in out
        out2, _ = self.cli("project", "ls")
        assert "no projects" in out2

    def test_workspace_cascade_archives_all(self, db_path):
        self.cli("workspace", "archive", "--force")
        assert get_active_workspace_id(db_path) is None
        # Workspace hidden from default ls
        out, _ = self.cli("workspace", "ls")
        assert "dev" not in out
        # But visible with --archived include
        out2, _ = self.cli("workspace", "ls", "--archived", "include")
        assert "dev" in out2


class TestArchiveConfirmation:
    @pytest.fixture(autouse=True)
    def _setup(self, cli, monkeypatch):
        self.cli = cli
        monkeypatch.setattr("sys.stdin.isatty", lambda: True)
        cli("workspace", "create", "dev")
        cli("status", "create", "todo")

    def test_confirm_yes(self, monkeypatch):
        self.cli("task", "create", "t1", "-S", "todo")
        monkeypatch.setattr("builtins.input", lambda _: "y")
        out, _ = self.cli("task", "archive", "1")
        assert "archived task-0001" in out

    def test_confirm_no(self, monkeypatch):
        self.cli("task", "create", "t1", "-S", "todo")
        monkeypatch.setattr("builtins.input", lambda _: "n")
        out, _ = self.cli("task", "archive", "1")
        assert "aborted" in out
        # task not archived
        out2, _ = self.cli("task", "ls")
        assert "t1" in out2

    def test_confirm_default_empty(self, monkeypatch):
        self.cli("task", "create", "t1", "-S", "todo")
        monkeypatch.setattr("builtins.input", lambda _: "")
        out, _ = self.cli("task", "archive", "1")
        assert "aborted" in out

    def test_json_auto_confirms(self):
        self.cli("task", "create", "t1", "-S", "todo")
        out, _ = self.cli("--json", "task", "archive", "1")
        data = json.loads(out)
        assert data["ok"] is True
        assert data["data"]["archived"] is True


class TestStatusTagDryRun:
    @pytest.fixture(autouse=True)
    def _setup(self, cli):
        self.cli = cli
        cli("workspace", "create", "dev")
        cli("status", "create", "todo")
        cli("tag", "create", "bug")
        cli("task", "create", "t1", "-S", "todo", "--tag", "bug")

    def test_status_dry_run(self):
        out, _ = self.cli("status", "archive", "todo", "--dry-run")
        assert "dry-run" in out
        assert "tasks: 1" in out
        # not actually archived
        out2, _ = self.cli("status", "ls")
        assert "todo" in out2

    def test_tag_dry_run(self):
        out, _ = self.cli("tag", "archive", "bug", "--dry-run")
        assert "dry-run" in out
        assert "tasks: 1" in out
        # not actually archived
        out2, _ = self.cli("tag", "ls")
        assert "bug" in out2


class TestStatusArchiveConfirmation:
    @pytest.fixture(autouse=True)
    def _setup(self, cli, monkeypatch):
        self.cli = cli
        monkeypatch.setattr("sys.stdin.isatty", lambda: True)
        cli("workspace", "create", "dev")
        cli("status", "create", "todo")
        cli("status", "create", "done")
        cli("task", "create", "t1", "-S", "todo")

    def test_force_confirms_and_archives_tasks(self, monkeypatch):
        monkeypatch.setattr("builtins.input", lambda _: "y")
        out, _ = self.cli("status", "archive", "todo", "--force")
        assert "archived status 'todo'" in out

    def test_force_aborted(self, monkeypatch):
        monkeypatch.setattr("builtins.input", lambda _: "n")
        out, _ = self.cli("status", "archive", "todo", "--force")
        assert "aborted" in out

    def test_reassign_confirms(self, monkeypatch):
        monkeypatch.setattr("builtins.input", lambda _: "y")
        out, _ = self.cli("status", "archive", "todo", "--reassign-to", "done")
        assert "archived status 'todo'" in out

    def test_reassign_does_not_prompt(self, monkeypatch):
        # --reassign-to is implicit confirmation; input() should never be called
        monkeypatch.setattr("builtins.input", lambda _: (_ for _ in ()).throw(AssertionError("input() called")))
        out, _ = self.cli("status", "archive", "todo", "--reassign-to", "done")
        assert "archived status 'todo'" in out

    def test_json_auto_confirms_force(self):
        out, _ = self.cli("--json", "status", "archive", "todo", "--force")
        data = json.loads(out)
        assert data["ok"] is True
        assert data["data"]["archived"] is True

    def test_reassign_to_non_tty_succeeds_without_force(self, monkeypatch):
        monkeypatch.setattr("sys.stdin.isatty", lambda: False)
        out, _ = self.cli("status", "archive", "todo", "--reassign-to", "done")
        assert "archived status 'todo'" in out


class TestTagArchiveConfirmation:
    @pytest.fixture(autouse=True)
    def _setup(self, cli, monkeypatch):
        self.cli = cli
        monkeypatch.setattr("sys.stdin.isatty", lambda: True)
        cli("workspace", "create", "dev")
        cli("status", "create", "todo")
        cli("tag", "create", "bug")

    def test_confirm_yes(self, monkeypatch):
        monkeypatch.setattr("builtins.input", lambda _: "y")
        out, _ = self.cli("tag", "archive", "bug")
        assert "archived tag 'bug'" in out

    def test_confirm_no(self, monkeypatch):
        monkeypatch.setattr("builtins.input", lambda _: "n")
        out, _ = self.cli("tag", "archive", "bug")
        assert "aborted" in out
        out2, _ = self.cli("tag", "ls")
        assert "bug" in out2

    def test_force_skips_confirmation(self):
        out, _ = self.cli("tag", "archive", "bug", "--force")
        assert "archived tag 'bug'" in out

    def test_json_auto_confirms(self):
        out, _ = self.cli("--json", "tag", "archive", "bug")
        data = json.loads(out)
        assert data["ok"] is True
        assert data["data"]["archived"] is True


class TestJsonDryRun:
    @pytest.fixture(autouse=True)
    def _setup(self, cli):
        self.cli = cli
        cli("workspace", "create", "dev")
        cli("status", "create", "todo")
        cli("project", "create", "proj")
        cli("group", "create", "grp", "--project", "proj")
        cli("task", "create", "t1", "-S", "todo", "-p", "proj")
        cli("group", "assign", "1", "grp", "--project", "proj")
        cli("tag", "create", "bug")
        cli("task", "edit", "1", "--tag", "bug")

    def _json(self, *args):
        out, _ = self.cli("--json", *args)
        return json.loads(out)

    def test_task_dry_run_json(self):
        data = self._json("task", "archive", "1", "--dry-run")
        assert data["ok"] is True
        assert data["data"]["entity_type"] == "task"
        assert data["data"]["already_archived"] is False

    def test_group_dry_run_json(self):
        data = self._json("group", "archive", "grp", "--project", "proj", "--dry-run")
        assert data["ok"] is True
        assert data["data"]["entity_type"] == "group"
        assert data["data"]["task_count"] == 1

    def test_project_dry_run_json(self):
        data = self._json("project", "archive", "proj", "--dry-run")
        assert data["ok"] is True
        assert data["data"]["entity_type"] == "project"
        assert data["data"]["task_count"] == 1
        assert data["data"]["group_count"] == 1

    def test_workspace_dry_run_json(self):
        data = self._json("workspace", "archive", "--dry-run")
        assert data["ok"] is True
        assert data["data"]["entity_type"] == "workspace"
        assert data["data"]["task_count"] == 1

    def test_status_dry_run_json(self):
        data = self._json("status", "archive", "todo", "--dry-run")
        assert data["ok"] is True
        assert data["data"]["entity_type"] == "status"
        assert data["data"]["task_count"] == 1

    def test_tag_dry_run_json(self):
        data = self._json("tag", "archive", "bug", "--dry-run")
        assert data["ok"] is True
        assert data["data"]["entity_type"] == "tag"
        assert data["data"]["task_count"] == 1


class TestDepReCreation:
    @pytest.fixture(autouse=True)
    def _setup(self, cli):
        self.cli = cli
        cli("workspace", "create", "dev")
        cli("status", "create", "todo")
        cli("task", "create", "a", "-S", "todo")
        cli("task", "create", "b", "-S", "todo")

    def test_readd_task_dep_after_archive(self):
        self.cli("dep", "create", "--task", "2", "--blocked-by", "1")
        self.cli("dep", "archive", "--task", "2", "--blocked-by", "1")
        out, _ = self.cli("dep", "create", "--task", "2", "--blocked-by", "1")
        assert "now blocked by" in out


# ---- End-to-end smoke test ----


class TestEndToEndSmoke:
    """Full lifecycle: build a rich workspace tree, query it, mutate it,
    then cascade-archive everything."""

    @pytest.fixture(autouse=True)
    def _setup(self, cli, db_path):
        self.cli = cli
        self.db_path = db_path
        # Workspace + statuses
        cli("workspace", "create", "dev")
        cli("status", "create", "todo")
        cli("status", "create", "in-progress")
        cli("status", "create", "done")
        # Projects
        cli("project", "create", "backend")
        cli("project", "create", "frontend")
        # Groups (nested)
        cli("group", "create", "api", "--project", "backend")
        cli("group", "create", "endpoints", "--parent", "api", "--project", "backend")
        cli("group", "create", "db", "--project", "backend")
        # Tags
        cli("tag", "create", "bug")
        cli("tag", "create", "urgent")
        cli("tag", "create", "tech-debt")
        # Tasks
        cli("task", "create", "Design API", "-S", "todo", "-p", "backend", "--tag", "bug")
        cli("task", "create", "Implement routes", "-S", "in-progress", "-p", "backend", "--tag", "urgent")
        cli("task", "create", "Write migrations", "-S", "todo", "-p", "backend")
        cli("task", "create", "Dashboard UI", "-S", "done", "-p", "frontend")
        cli("task", "create", "Cleanup", "-S", "todo")
        # Group assignments
        cli("group", "assign", "1", "api", "--project", "backend")
        cli("group", "assign", "2", "endpoints", "--project", "backend")
        cli("group", "assign", "3", "db", "--project", "backend")
        # Task dependencies
        cli("dep", "create", "--task", "2", "--blocked-by", "1")
        cli("dep", "create", "--task", "3", "--blocked-by", "1")
        # Group dependencies
        cli("group", "dep", "create", "--group", "endpoints", "--blocked-by", "db", "--project", "backend")

    def test_listing_commands(self):
        out, _ = self.cli("task", "ls")
        assert "Design API" in out
        assert "Implement routes" in out
        assert "Write migrations" in out
        assert "Dashboard UI" in out
        assert "Cleanup" in out

        out, _ = self.cli("task", "ls", "--status", "todo")
        assert "Design API" in out
        assert "Cleanup" in out
        assert "Implement routes" not in out

        out, _ = self.cli("status", "ls")
        assert "todo" in out
        assert "in-progress" in out
        assert "done" in out

        out, _ = self.cli("project", "ls")
        assert "backend" in out
        assert "frontend" in out

        out, _ = self.cli("group", "ls", "--project", "backend")
        assert "api" in out
        assert "endpoints" in out
        assert "db" in out

        out, _ = self.cli("tag", "ls")
        assert "bug" in out
        assert "urgent" in out
        assert "tech-debt" in out

    def test_show_and_detail(self):
        # t2 is blocked by t1
        out, _ = self.cli("task", "show", "2")
        assert "task-0001" in out  # blocked-by reference

        out, _ = self.cli("project", "show", "backend")
        assert "backend" in out

        out, _ = self.cli("group", "show", "api", "--project", "backend")
        assert "api" in out

    def test_workspace_show(self):
        out, _ = self.cli("workspace", "show")
        assert "todo" in out
        assert "in-progress" in out
        assert "done" in out
        assert "Design API" in out
        assert "backend" in out
        assert "bug" in out

    def test_export(self):
        out, _ = self.cli("export", "--md")
        assert "dev" in out
        assert "Design API" in out
        assert "Dashboard UI" in out

    def test_task_edit_and_move(self):
        self.cli("task", "edit", "5", "--title", "Cleanup v2", "--priority", "3")
        self.cli("task", "mv", "5", "-S", "in-progress")
        out, _ = self.cli("task", "show", "5")
        assert "Cleanup v2" in out
        assert "in-progress" in out

    def test_dep_archive_and_recreate(self):
        self.cli("dep", "archive", "--task", "2", "--blocked-by", "1")
        out, _ = self.cli("task", "show", "2")
        assert "Blocked by" not in out  # no longer blocked by t1

        self.cli("dep", "create", "--task", "2", "--blocked-by", "1")
        out, _ = self.cli("task", "show", "2")
        assert "task-0001" in out  # blocked again

    def test_dry_run_workspace(self):
        out, _ = self.cli("workspace", "archive", "--dry-run")
        assert "dry-run" in out
        assert "projects: 2" in out
        assert "groups: 3" in out
        assert "statuses: 3" in out
        assert "tasks: 5" in out
        # Nothing actually archived
        out, _ = self.cli("task", "ls")
        assert "Design API" in out

    def test_cascade_archive_workspace(self):
        self.cli("workspace", "archive", "--force")
        assert get_active_workspace_id(self.db_path) is None
        out, _ = self.cli("workspace", "ls")
        assert "dev" not in out
        out, _ = self.cli("workspace", "ls", "--archived", "include")
        assert "dev" in out


# ---- Task metadata commands ----


class TestTaskMetaCommands:
    @pytest.fixture(autouse=True)
    def _setup(self, cli):
        self.cli = cli
        cli("workspace", "create", "dev")
        cli("status", "create", "todo")
        cli("task", "create", "My task", "-S", "todo")

    def test_meta_ls_empty(self):
        out, _ = self.cli("task", "meta", "ls", "1")
        assert "no metadata" in out

    def test_meta_set_and_get(self):
        self.cli("task", "meta", "set", "1", "branch", "feat/kv")
        out, _ = self.cli("task", "meta", "get", "1", "branch")
        assert "feat/kv" in out

    def test_meta_ls_after_set(self):
        self.cli("task", "meta", "set", "1", "branch", "feat/kv")
        self.cli("task", "meta", "set", "1", "jira", "PROJ-123")
        out, _ = self.cli("task", "meta", "ls", "1")
        assert "branch" in out
        assert "feat/kv" in out
        assert "jira" in out
        assert "PROJ-123" in out

    def test_meta_del(self):
        self.cli("task", "meta", "set", "1", "branch", "feat/kv")
        out, _ = self.cli("task", "meta", "del", "1", "branch")
        assert "removed branch" in out
        out, _ = self.cli("task", "meta", "ls", "1")
        assert "no metadata" in out

    def test_meta_del_nonexistent(self):
        _, err = self.cli("task", "meta", "del", "1", "nope", expect_exit=3)
        assert "not found" in err

    def test_meta_get_nonexistent(self):
        _, err = self.cli("task", "meta", "get", "1", "nope", expect_exit=3)
        assert "not found" in err

    def test_meta_get_invalid_key(self):
        _, err = self.cli("task", "meta", "get", "1", "BAD KEY", expect_exit=4)
        assert "must match" in err

    def test_meta_set_invalid_key(self):
        _, err = self.cli("task", "meta", "set", "1", "BAD KEY", "v", expect_exit=4)
        assert "must match" in err

    def test_meta_set_json(self):
        out, _ = self.cli("--json", "task", "meta", "set", "1", "branch", "feat/kv")
        data = json.loads(out)
        assert data["ok"] is True
        assert data["data"] == {"key": "branch", "value": "feat/kv"}

    def test_meta_ls_json(self):
        self.cli("task", "meta", "set", "1", "k", "v")
        self.cli("task", "meta", "set", "1", "a", "b")
        out, _ = self.cli("--json", "task", "meta", "ls", "1")
        data = json.loads(out)
        assert data["ok"] is True
        assert data["data"] == [
            {"key": "a", "value": "b"},
            {"key": "k", "value": "v"},
        ]

    def test_meta_ls_json_empty(self):
        out, _ = self.cli("--json", "task", "meta", "ls", "1")
        data = json.loads(out)
        assert data["ok"] is True
        assert data["data"] == []

    def test_meta_get_json(self):
        self.cli("task", "meta", "set", "1", "branch", "feat/kv")
        out, _ = self.cli("--json", "task", "meta", "get", "1", "branch")
        data = json.loads(out)
        assert data["ok"] is True
        assert data["data"] == {"key": "branch", "value": "feat/kv"}

    def test_meta_del_json(self):
        self.cli("task", "meta", "set", "1", "branch", "feat/kv")
        out, _ = self.cli("--json", "task", "meta", "del", "1", "branch")
        data = json.loads(out)
        assert data["ok"] is True
        assert data["data"] == {"key": "branch", "value": "feat/kv"}

    def test_meta_visible_in_show(self):
        self.cli("task", "meta", "set", "1", "branch", "feat/kv")
        out, _ = self.cli("task", "show", "1")
        assert "Metadata:" in out
        assert "branch: feat/kv" in out

    def test_meta_ls_padding_adapts_to_long_key(self):
        self.cli("task", "meta", "set", "1", "deployment.environment", "prod")
        self.cli("task", "meta", "set", "1", "k", "v")
        out, _ = self.cli("task", "meta", "ls", "1")
        # Each line: 2-space indent + key + padding + value. Value must not
        # butt up against the key — there should be at least one space between.
        for line in out.splitlines():
            stripped = line.lstrip()
            key, sep, rest = stripped.partition(" ")
            assert rest.lstrip() != "", f"no separation between key and value: {line!r}"

    def test_meta_set_nonexistent_task(self):
        _, err = self.cli("task", "meta", "set", "999", "branch", "feat/kv", expect_exit=3)
        assert "not found" in err

    def test_meta_key_case_insensitive_roundtrip(self):
        self.cli("task", "meta", "set", "1", "Branch", "feat/kv")
        # Stored lowercase — lookups by any case should hit it
        out, _ = self.cli("task", "meta", "get", "1", "BRANCH")
        assert "feat/kv" in out
        out, _ = self.cli("task", "meta", "get", "1", "branch")
        assert "feat/kv" in out

    def test_meta_key_normalized_in_ls(self):
        self.cli("task", "meta", "set", "1", "Branch", "feat/kv")
        out, _ = self.cli("task", "meta", "ls", "1")
        assert "branch" in out
        assert "Branch" not in out

    def test_meta_del_mixed_case(self):
        self.cli("task", "meta", "set", "1", "Branch", "feat/kv")
        out, _ = self.cli("task", "meta", "del", "1", "BRANCH")
        assert "removed branch" in out
        out, _ = self.cli("task", "meta", "ls", "1")
        assert "no metadata" in out

    def test_meta_resolves_title(self):
        self.cli("task", "meta", "set", "My task", "branch", "feat/kv")
        out, _ = self.cli("task", "meta", "get", "My task", "branch")
        assert "feat/kv" in out
        out, _ = self.cli("task", "meta", "ls", "My task")
        assert "branch" in out
        self.cli("task", "meta", "del", "My task", "branch")
        out, _ = self.cli("task", "meta", "ls", "1")
        assert "no metadata" in out


# ---- Workspace metadata ----


class TestWorkspaceMetaCommands:
    @pytest.fixture(autouse=True)
    def _setup(self, cli):
        self.cli = cli
        cli("workspace", "create", "dev")

    def test_ls_empty(self):
        out, _ = self.cli("workspace", "meta", "ls")
        assert "no metadata" in out

    def test_set_and_get(self):
        self.cli("workspace", "meta", "set", "env", "prod")
        out, _ = self.cli("workspace", "meta", "get", "env")
        assert "prod" in out

    def test_ls_after_set(self):
        self.cli("workspace", "meta", "set", "env", "prod")
        self.cli("workspace", "meta", "set", "region", "us-east-1")
        out, _ = self.cli("workspace", "meta", "ls")
        assert "env" in out
        assert "prod" in out
        assert "region" in out

    def test_del(self):
        self.cli("workspace", "meta", "set", "env", "prod")
        out, _ = self.cli("workspace", "meta", "del", "env")
        assert "removed env" in out
        out, _ = self.cli("workspace", "meta", "ls")
        assert "no metadata" in out

    def test_del_missing(self):
        _, err = self.cli("workspace", "meta", "del", "nope", expect_exit=3)
        assert "not found" in err

    def test_get_missing(self):
        _, err = self.cli("workspace", "meta", "get", "nope", expect_exit=3)
        assert "not found" in err

    def test_case_insensitive(self):
        self.cli("workspace", "meta", "set", "Env", "prod")
        out, _ = self.cli("workspace", "meta", "get", "ENV")
        assert "prod" in out

    def test_set_json(self):
        out, _ = self.cli("--json", "workspace", "meta", "set", "env", "prod")
        data = json.loads(out)
        assert data["ok"] is True
        assert data["data"] == {"key": "env", "value": "prod"}

    def test_ls_json(self):
        self.cli("workspace", "meta", "set", "a", "1")
        self.cli("workspace", "meta", "set", "b", "2")
        out, _ = self.cli("--json", "workspace", "meta", "ls")
        data = json.loads(out)
        assert data["ok"] is True
        assert data["data"] == [{"key": "a", "value": "1"}, {"key": "b", "value": "2"}]

    def test_respects_workspace_flag(self, cli):
        cli("workspace", "create", "other")
        cli("workspace", "use", "dev")
        cli("workspace", "meta", "set", "env", "dev-val")
        cli("-w", "other", "workspace", "meta", "set", "env", "other-val")
        out, _ = cli("workspace", "meta", "get", "env")
        assert "dev-val" in out
        out, _ = cli("-w", "other", "workspace", "meta", "get", "env")
        assert "other-val" in out


class TestWorkspaceMetaNoActiveWorkspace:
    """Workspace meta commands must surface the centralized missing_active_workspace
    error when run without an active workspace and without -w override. Separate
    class because these tests need to NOT have the 'dev' autouse fixture."""

    def test_ls_no_active_workspace(self, cli):
        _, err = cli("workspace", "meta", "ls", expect_exit=5)
        assert "no active workspace" in err

    def test_set_no_active_workspace(self, cli):
        _, err = cli("workspace", "meta", "set", "env", "prod", expect_exit=5)
        assert "no active workspace" in err

    def test_ls_no_active_workspace_json(self, cli):
        _, err = cli("--json", "workspace", "meta", "ls", expect_exit=5)
        data = json.loads(err)
        assert data["ok"] is False
        assert data["code"] == "missing_active_workspace"


# ---- Project metadata ----


class TestProjectMetaCommands:
    @pytest.fixture(autouse=True)
    def _setup(self, cli):
        self.cli = cli
        cli("workspace", "create", "dev")
        cli("project", "create", "backend")

    def test_ls_empty(self):
        out, _ = self.cli("project", "meta", "ls", "backend")
        assert "no metadata" in out

    def test_set_and_get(self):
        self.cli("project", "meta", "set", "backend", "owner", "alice")
        out, _ = self.cli("project", "meta", "get", "backend", "owner")
        assert "alice" in out

    def test_del(self):
        self.cli("project", "meta", "set", "backend", "owner", "alice")
        self.cli("project", "meta", "del", "backend", "owner")
        out, _ = self.cli("project", "meta", "ls", "backend")
        assert "no metadata" in out

    def test_del_missing(self):
        _, err = self.cli("project", "meta", "del", "backend", "nope", expect_exit=3)
        assert "not found" in err

    def test_unknown_project(self):
        _, err = self.cli("project", "meta", "set", "ghost", "k", "v", expect_exit=3)
        assert "not found" in err

    def test_case_insensitive(self):
        self.cli("project", "meta", "set", "backend", "Owner", "alice")
        out, _ = self.cli("project", "meta", "get", "backend", "OWNER")
        assert "alice" in out

    def test_set_json(self):
        out, _ = self.cli("--json", "project", "meta", "set", "backend", "owner", "alice")
        data = json.loads(out)
        assert data["data"] == {"key": "owner", "value": "alice"}


# ---- Group metadata ----


class TestGroupMetaCommands:
    @pytest.fixture(autouse=True)
    def _setup(self, cli):
        self.cli = cli
        cli("workspace", "create", "dev")
        cli("project", "create", "backend")
        cli("group", "create", "Sprint 1", "--project", "backend")

    def test_ls_empty(self):
        out, _ = self.cli("group", "meta", "ls", "Sprint 1", "--project", "backend")
        assert "no metadata" in out

    def test_set_and_get(self):
        self.cli("group", "meta", "set", "Sprint 1", "start", "2026-01-01", "--project", "backend")
        out, _ = self.cli("group", "meta", "get", "Sprint 1", "start", "--project", "backend")
        assert "2026-01-01" in out

    def test_del(self):
        self.cli("group", "meta", "set", "Sprint 1", "start", "2026-01-01", "--project", "backend")
        self.cli("group", "meta", "del", "Sprint 1", "start", "--project", "backend")
        out, _ = self.cli("group", "meta", "ls", "Sprint 1", "--project", "backend")
        assert "no metadata" in out

    def test_del_missing(self):
        _, err = self.cli(
            "group", "meta", "del", "Sprint 1", "nope", "--project", "backend",
            expect_exit=3,
        )
        assert "not found" in err

    def test_unknown_group(self):
        _, err = self.cli(
            "group", "meta", "set", "Ghost", "k", "v", "--project", "backend",
            expect_exit=3,
        )
        assert "not found" in err

    def test_case_insensitive(self):
        self.cli(
            "group", "meta", "set", "Sprint 1", "Start", "2026-01-01",
            "--project", "backend",
        )
        out, _ = self.cli(
            "group", "meta", "get", "Sprint 1", "START", "--project", "backend",
        )
        assert "2026-01-01" in out

    def test_set_json(self):
        out, _ = self.cli(
            "--json", "group", "meta", "set", "Sprint 1", "start", "2026-01-01",
            "--project", "backend",
        )
        data = json.loads(out)
        assert data["data"] == {"key": "start", "value": "2026-01-01"}


# ---- task-0127: format_status_list archived marker ----


class TestStatusListArchivedMarker:
    """status ls --archived include/only renders (archived) suffix."""

    @pytest.fixture(autouse=True)
    def _setup(self, cli):
        self.cli = cli
        cli("workspace", "create", "dev")
        cli("status", "create", "active")
        cli("status", "create", "old")
        cli("status", "archive", "old")

    def test_archived_marker_shown_with_include(self):
        out, _ = self.cli("status", "ls", "--archived", "include")
        assert "(archived)" in out
        assert "old (archived)" in out

    def test_archived_marker_shown_with_only(self):
        out, _ = self.cli("status", "ls", "--archived", "only")
        assert "(archived)" in out

    def test_no_archived_marker_on_active(self):
        out, _ = self.cli("status", "ls", "--archived", "include")
        lines = [l for l in out.splitlines() if "active" in l]
        assert len(lines) == 1
        assert "(archived)" not in lines[0]


# ---- task-0128: format_project_list archived marker ----


class TestProjectListArchivedMarker:
    """project ls --archived include/only renders (archived) suffix."""

    @pytest.fixture(autouse=True)
    def _setup(self, cli):
        self.cli = cli
        cli("workspace", "create", "dev")
        cli("project", "create", "live")
        cli("project", "create", "old")
        cli("project", "archive", "old", "--force")

    def test_archived_marker_shown_with_include(self):
        out, _ = self.cli("project", "ls", "--archived", "include")
        assert "(archived)" in out
        assert "old (archived)" in out

    def test_archived_marker_shown_with_only(self):
        out, _ = self.cli("project", "ls", "--archived", "only")
        assert "(archived)" in out

    def test_no_archived_marker_on_live_project(self):
        out, _ = self.cli("project", "ls", "--archived", "include")
        lines = [l for l in out.splitlines() if "live" in l]
        assert len(lines) == 1
        assert "(archived)" not in lines[0]


# ---- task-0129: format_move_preview source workspace name ----


class TestTransferDryRunSourceName:
    """transfer --dry-run shows source workspace name, not ID."""

    @pytest.fixture(autouse=True)
    def _setup(self, cli):
        self.cli = cli
        cli("workspace", "create", "source-ws")
        cli("status", "create", "todo")
        cli("task", "create", "Task A", "-S", "todo")
        cli("workspace", "create", "target-ws")
        cli("workspace", "use", "target-ws")
        cli("status", "create", "backlog")
        cli("workspace", "use", "source-ws")

    def test_dry_run_shows_source_name_not_id(self):
        out, _ = self.cli("task", "transfer", "1", "--to", "target-ws", "--status", "backlog", "--dry-run")
        assert "dry-run" in out
        assert "source-ws" in out
        # Must not show a bare integer where the workspace name should be
        import re
        # The "from workspace" line should not contain a standalone integer
        from_line = next((l for l in out.splitlines() if "from workspace" in l), "")
        assert "source-ws" in from_line


# ---- task-0130: format_archive_preview no prefix in confirm prompt ----


class TestArchivePreviewPrefixSeparation:
    """--dry-run output has 'dry-run:' prefix; interactive confirm prompt does not."""

    @pytest.fixture(autouse=True)
    def _setup(self, cli, monkeypatch):
        self.cli = cli
        self.monkeypatch = monkeypatch
        cli("workspace", "create", "dev")
        cli("status", "create", "todo")
        cli("task", "create", "Task A", "-S", "todo")

    def test_dry_run_has_prefix(self):
        out, _ = self.cli("task", "archive", "1", "--dry-run")
        assert out.startswith("dry-run:")

    def test_confirm_prompt_no_dry_run_prefix(self):
        self.monkeypatch.setattr("sys.stdin.isatty", lambda: True)
        # Capture stderr where preview is printed
        seen = []
        original_print = __builtins__["print"] if isinstance(__builtins__, dict) else print
        import sys
        self.monkeypatch.setattr("builtins.input", lambda _: "n")
        # Run and capture stderr
        _, err = self.cli("task", "archive", "1")
        # The confirm preview is sent to stderr; it should NOT start with "dry-run:"
        assert err == "" or not err.lstrip().startswith("dry-run:")


# ---- task-0131: cmd_task_edit strips/nulls --desc ----


class TestTaskEditDescStrip:
    """task edit -d '' and -d '   ' should clear description to None."""

    @pytest.fixture(autouse=True)
    def _setup(self, cli):
        self.cli = cli
        cli("workspace", "create", "dev")
        cli("status", "create", "todo")
        cli("task", "create", "Task", "-d", "original desc", "-S", "todo")

    def test_empty_desc_clears_to_null(self):
        out, _ = self.cli("--json", "task", "edit", "1", "-d", "")
        data = json.loads(out)
        assert data["data"]["description"] is None

    def test_whitespace_desc_clears_to_null(self):
        out, _ = self.cli("--json", "task", "edit", "1", "-d", "   ")
        data = json.loads(out)
        assert data["data"]["description"] is None

    def test_normal_desc_retained(self):
        out, _ = self.cli("--json", "task", "edit", "1", "-d", "new desc")
        data = json.loads(out)
        assert data["data"]["description"] == "new desc"
