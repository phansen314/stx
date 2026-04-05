from __future__ import annotations

from sticky_notes import presenters
from sticky_notes.models import (
    Board,
    Column,
    Group,
    Project,
    Tag,
    Task,
    TaskField,
    TaskHistory,
)
from sticky_notes.service_models import (
    BoardListColumn,
    BoardListView,
    GroupDetail,
    GroupRef,
    GroupTreeNode,
    MoveToBoardPreview,
    ProjectDetail,
    ProjectGroupTree,
    TaskDetail,
    TaskListItem,
)


# ---- factories (structural, no DB) ----


def _board(id: int = 1, name: str = "B", archived: bool = False) -> Board:
    return Board(id=id, name=name, archived=archived, created_at=0)


def _column(id: int, name: str, position: int = 0, archived: bool = False) -> Column:
    return Column(id=id, board_id=1, name=name, position=position, archived=archived, created_at=0)


def _project(id: int, name: str, description: str | None = None) -> Project:
    return Project(
        id=id, board_id=1, name=name, description=description, archived=False, created_at=0,
    )


def _tag(id: int, name: str, archived: bool = False) -> Tag:
    return Tag(id=id, board_id=1, name=name, archived=archived, created_at=0)


def _task(
    id: int, title: str, *,
    column_id: int = 1, priority: int = 1,
    due_date: int | None = None, project_id: int | None = None,
) -> Task:
    return Task(
        id=id, board_id=1, title=title,
        project_id=project_id, description=None, column_id=column_id,
        priority=priority, due_date=due_date, position=0, archived=False,
        created_at=0, start_date=None, finish_date=None, group_id=None,
    )


def _list_item(
    id: int, title: str, *,
    column_id: int = 1, priority: int = 1,
    project_name: str | None = None, tag_names: tuple[str, ...] = (),
) -> TaskListItem:
    return TaskListItem(
        id=id, board_id=1, title=title,
        project_id=None, description=None, column_id=column_id,
        priority=priority, due_date=None, position=0, archived=False,
        created_at=0, start_date=None, finish_date=None, group_id=None,
        project_name=project_name, tag_names=tag_names,
    )


def _history(
    id: int, field: TaskField, old: str | None, new: str | None, source: str = "cli",
) -> TaskHistory:
    return TaskHistory(
        id=id, task_id=1, field=field, old_value=old, new_value=new,
        source=source, changed_at=0,
    )


# ---- format_history_entry / format_task_history ----


class TestHistoryFormatter:
    def test_empty_history_shows_placeholder(self):
        assert presenters.format_task_history(()) == "no history"

    def test_entry_format(self):
        h = _history(1, TaskField.TITLE, "old", "new")
        out = presenters.format_history_entry(h)
        assert "title" in out
        assert "old -> new" in out
        assert "(cli)" in out

    def test_none_values_show_placeholder(self):
        h = _history(1, TaskField.DUE_DATE, None, "2026-01-01")
        out = presenters.format_history_entry(h)
        assert "(none) -> 2026-01-01" in out

    def test_multiple_entries_joined(self):
        h1 = _history(1, TaskField.TITLE, "a", "b")
        h2 = _history(2, TaskField.PRIORITY, "1", "3")
        out = presenters.format_task_history((h1, h2))
        assert out.count("\n") == 1


# ---- format_board_list ----


class TestFormatBoardList:
    def test_empty(self):
        assert presenters.format_board_list((), None) == "no boards"

    def test_active_marker(self):
        boards = (_board(1, "A"), _board(2, "B"))
        out = presenters.format_board_list(boards, active_id=2)
        assert "  A\n  B *" == out

    def test_archived_marker(self):
        boards = (_board(1, "A", archived=True),)
        out = presenters.format_board_list(boards, active_id=None)
        assert "(archived)" in out

    def test_active_and_archived(self):
        boards = (_board(1, "A", archived=True),)
        out = presenters.format_board_list(boards, active_id=1)
        assert " *" in out
        assert "(archived)" in out


# ---- format_column_list ----


class TestFormatColumnList:
    def test_empty(self):
        assert presenters.format_column_list(()) == "no columns"

    def test_shows_position_and_name(self):
        cols = (_column(1, "Todo", 0), _column(2, "Done", 1))
        out = presenters.format_column_list(cols)
        assert out == "  0  Todo\n  1  Done"


# ---- format_project_list ----


class TestFormatProjectList:
    def test_empty(self):
        assert presenters.format_project_list(()) == "no projects"

    def test_no_description(self):
        projs = (_project(1, "P"),)
        assert presenters.format_project_list(projs) == "  P"

    def test_with_description(self):
        projs = (_project(1, "P", description="a desc"),)
        out = presenters.format_project_list(projs)
        assert "P" in out
        assert "a desc" in out


# ---- format_project_detail ----


class TestFormatProjectDetail:
    def test_empty_tasks(self):
        detail = ProjectDetail(
            id=1, board_id=1, name="P", description=None,
            archived=False, created_at=0, tasks=(),
        )
        out = presenters.format_project_detail(detail)
        assert "P" in out
        assert "Tasks: 0" in out

    def test_with_description_and_tasks(self):
        detail = ProjectDetail(
            id=1, board_id=1, name="P", description="desc",
            archived=False, created_at=0,
            tasks=(_task(5, "work"),),
        )
        out = presenters.format_project_detail(detail)
        assert "desc" in out
        assert "Tasks: 1" in out
        assert "task-0005" in out
        assert "work" in out


# ---- format_tag_list ----


class TestFormatTagList:
    def test_empty(self):
        assert presenters.format_tag_list(()) == "no tags"

    def test_with_archived(self):
        tags = (_tag(1, "bug"), _tag(2, "old", archived=True))
        out = presenters.format_tag_list(tags)
        assert "  bug" in out
        assert "  old (archived)" in out


# ---- format_task_detail ----


class TestFormatTaskDetail:
    def _detail(self, **overrides) -> TaskDetail:
        base = dict(
            id=7, board_id=1, title="T", project_id=None, description=None,
            column_id=1, priority=2, due_date=None, position=0, archived=False,
            created_at=0, start_date=None, finish_date=None, group_id=None,
            column=_column(1, "Todo"), project=None, group=None,
            blocked_by=(), blocks=(), history=(), tags=(),
        )
        base.update(overrides)
        return TaskDetail(**base)

    def test_minimal(self):
        out = presenters.format_task_detail(self._detail())
        assert "task-0007  T" in out
        assert "Column:      Todo" in out
        assert "Priority:    2" in out
        # optional fields absent
        assert "Due:" not in out
        assert "Description:" not in out

    def test_with_all_fields(self):
        d = self._detail(
            project=_project(5, "proj"),
            project_id=5,
            group=Group(id=3, project_id=5, title="g", parent_id=None, position=0, archived=False, created_at=0),
            tags=(_tag(1, "bug"), _tag(2, "urgent")),
            description="do the thing",
            due_date=1_000_000,
            blocked_by=(_task(2, "blocker"),),
            blocks=(_task(3, "blocked"),),
            history=(_history(1, TaskField.TITLE, "old", "T"),),
        )
        out = presenters.format_task_detail(d)
        assert "Project:     proj" in out
        assert "Group:       g (group-0003)" in out
        assert "Tags:        bug, urgent" in out
        assert "Due:" in out
        assert "Blocked by:  task-0002" in out
        assert "Blocks:      task-0003" in out
        assert "Description:" in out
        assert "do the thing" in out
        assert "History:" in out
        assert "    " in out  # history lines are indented


# ---- format_board_list_view ----


class TestFormatBoardListView:
    def test_columns_with_headers(self):
        view = BoardListView(
            board=_board(1, "B"),
            columns=(
                BoardListColumn(column=_column(1, "Todo", 0), tasks=()),
                BoardListColumn(column=_column(2, "Done", 1), tasks=()),
            ),
        )
        out = presenters.format_board_list_view(view)
        assert "== Todo ==" in out
        assert "== Done ==" in out
        assert "(empty)" in out

    def test_task_rendering(self):
        view = BoardListView(
            board=_board(1),
            columns=(
                BoardListColumn(
                    column=_column(1, "Todo"),
                    tasks=(_list_item(1, "do it", priority=3, project_name="proj", tag_names=("bug",)),),
                ),
            ),
        )
        out = presenters.format_board_list_view(view)
        assert "task-0001" in out
        assert "[P3]" in out
        assert "do it" in out
        assert "@proj" in out
        assert "[bug]" in out

    def test_no_project_or_tags(self):
        view = BoardListView(
            board=_board(1),
            columns=(
                BoardListColumn(
                    column=_column(1, "Todo"),
                    tasks=(_list_item(1, "bare"),),
                ),
            ),
        )
        out = presenters.format_board_list_view(view)
        assert out.endswith("bare")  # no trailing @proj or [tags] segment
        assert "@" not in out


# ---- format_group_list ----


class TestFormatGroupList:
    def _ref(self, id: int, title: str, *, archived: bool = False, task_count: int = 0) -> GroupRef:
        return GroupRef(
            id=id, project_id=1, title=title, parent_id=None, position=0,
            archived=archived, created_at=0,
            task_ids=tuple(range(task_count)), child_ids=(),
        )

    def test_no_sections(self):
        assert presenters.format_group_list(()) == "no projects"

    def test_single_project_empty(self):
        sections = ((_project(1, "P"), ()),)
        assert presenters.format_group_list(sections) == "no groups"

    def test_single_project_no_headers(self):
        sections = ((_project(1, "P"), (self._ref(1, "G", task_count=2),)),)
        out = presenters.format_group_list(sections)
        assert "== P ==" not in out
        assert "group-0001" in out
        assert "(2 tasks)" in out

    def test_multi_project_headers(self):
        sections = (
            (_project(1, "P1"), (self._ref(1, "G1"),)),
            (_project(2, "P2"), (self._ref(2, "G2"),)),
        )
        out = presenters.format_group_list(sections)
        assert "== P1 ==" in out
        assert "== P2 ==" in out

    def test_archived_marker(self):
        sections = ((_project(1, "P"), (self._ref(1, "G", archived=True),)),)
        out = presenters.format_group_list(sections)
        assert "(archived)" in out


# ---- format_group_trees ----


class TestFormatGroupTrees:
    def _node(self, id: int, title: str, children=()) -> GroupTreeNode:
        ref = GroupRef(
            id=id, project_id=1, title=title, parent_id=None, position=0,
            archived=False, created_at=0, task_ids=(), child_ids=(),
        )
        return GroupTreeNode(group=ref, children=children)

    def test_empty(self):
        assert presenters.format_group_trees(()) == "no projects"

    def test_single_root(self):
        tree = ProjectGroupTree(project_id=1, roots=(self._node(1, "Root"),), ungrouped_task_count=0)
        sections = ((_project(1, "P"), tree, {}),)
        out = presenters.format_group_trees(sections)
        assert "group-0001" in out
        assert "Root" in out

    def test_nested(self):
        # Tree rendering preserves existing behavior: top-level children
        # render without connectors/indentation (prefix="" stays "").
        grandchild = self._node(3, "GrandChild")
        child = self._node(2, "Child", children=(grandchild,))
        root = self._node(1, "Root", children=(child,))
        tree = ProjectGroupTree(project_id=1, roots=(root,), ungrouped_task_count=0)
        sections = ((_project(1, "P"), tree, {}),)
        out = presenters.format_group_trees(sections)
        assert "group-0001  Root" in out
        assert "group-0002  Child" in out
        assert "group-0003  GrandChild" in out

    def test_ungrouped_count_shown(self):
        tree = ProjectGroupTree(project_id=1, roots=(self._node(1, "R"),), ungrouped_task_count=3)
        sections = ((_project(1, "P"), tree, {}),)
        out = presenters.format_group_trees(sections)
        assert "3 ungrouped tasks" in out

    def test_multi_project_headers(self):
        t1 = ProjectGroupTree(project_id=1, roots=(self._node(1, "R1"),), ungrouped_task_count=0)
        t2 = ProjectGroupTree(project_id=2, roots=(self._node(2, "R2"),), ungrouped_task_count=0)
        sections = (
            (_project(1, "P1"), t1, {}),
            (_project(2, "P2"), t2, {}),
        )
        out = presenters.format_group_trees(sections)
        assert "== P1 ==" in out
        assert "== P2 ==" in out


# ---- format_group_detail ----


class TestFormatGroupDetail:
    def test_minimal(self):
        d = GroupDetail(
            id=1, project_id=1, title="G", parent_id=None, position=0,
            archived=False, created_at=0,
            tasks=(), children=(), parent=None,
        )
        out = presenters.format_group_detail(d, project_name="P", ancestry_titles=("G",))
        assert "Group: G (group-0001)" in out
        assert "Project: P" in out
        assert "Path:    G" in out
        assert "Tasks:   0" in out

    def test_with_children_and_tasks(self):
        child = Group(id=2, project_id=1, title="ChildA", parent_id=1, position=0, archived=False, created_at=0)
        d = GroupDetail(
            id=1, project_id=1, title="Root", parent_id=None, position=0,
            archived=False, created_at=0,
            tasks=(_task(10, "work", priority=3, due_date=1_000_000),),
            children=(child,), parent=None,
        )
        out = presenters.format_group_detail(d, project_name="P", ancestry_titles=("Root",))
        assert "Sub-groups: ChildA" in out
        assert "task-0010" in out
        assert "[P3]" in out
        assert "work" in out
        assert "due:" in out


# ---- format_move_preview ----


class TestFormatMovePreview:
    def _preview(self, **overrides) -> MoveToBoardPreview:
        base = dict(
            task_id=5, task_title="T", source_board_id=1, target_board_id=2,
            target_column_id=3, can_move=True, blocking_reason=None,
            dependency_ids=(), is_archived=False,
        )
        base.update(overrides)
        return MoveToBoardPreview(**base)

    def test_can_move(self):
        out = presenters.format_move_preview(self._preview(), "other", "Backlog")
        assert "dry-run" in out
        assert "task-0005" in out
        assert "board 'other' / column 'Backlog'" in out
        assert "transfer OK" in out

    def test_blocked_by_dependencies(self):
        p = self._preview(can_move=False, dependency_ids=(10, 11))
        out = presenters.format_move_preview(p, "other", "Backlog")
        assert "has dependencies: task-0010, task-0011" in out
        assert "move would FAIL" in out

    def test_blocked_other_reason(self):
        p = self._preview(can_move=False, blocking_reason="task is archived")
        out = presenters.format_move_preview(p, "other", "Backlog")
        assert "task is archived" in out
        assert "move would FAIL" in out
