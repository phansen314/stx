from __future__ import annotations

from stx import presenters
from stx.models import (
    EntityType,
    Group,
    JournalEntry,
    Status,
    Tag,
    Task,
    TaskField,
    Workspace,
)
from stx.service_models import (
    ArchivePreview,
    EdgeRef,
    GroupDetail,
    GroupRef,
    MoveToWorkspacePreview,
    TaskDetail,
    TaskListItem,
    WorkspaceContext,
    WorkspaceListStatus,
    WorkspaceListView,
)

# ---- factories (structural, no DB) ----


def _workspace(id: int = 1, name: str = "B", archived: bool = False) -> Workspace:
    return Workspace(id=id, name=name, archived=archived, created_at=0, metadata={})


def _status(id: int, name: str, archived: bool = False) -> Status:
    return Status(id=id, workspace_id=1, name=name, archived=archived, created_at=0)


def _tag(id: int, name: str, archived: bool = False) -> Tag:
    return Tag(id=id, workspace_id=1, name=name, archived=archived, created_at=0)


def _task(
    id: int,
    title: str,
    *,
    status_id: int = 1,
    priority: int = 1,
    due_date: int | None = None,
) -> Task:
    return Task(
        id=id,
        workspace_id=1,
        title=title,
        description=None,
        status_id=status_id,
        priority=priority,
        due_date=due_date,
        position=0,
        archived=False,
        created_at=0,
        start_date=None,
        finish_date=None,
        group_id=None,
        metadata={},
    )


def _list_item(
    id: int,
    title: str,
    *,
    status_id: int = 1,
    priority: int = 1,
    tag_names: tuple[str, ...] = (),
) -> TaskListItem:
    return TaskListItem(
        id=id,
        workspace_id=1,
        title=title,
        description=None,
        status_id=status_id,
        priority=priority,
        due_date=None,
        position=0,
        archived=False,
        created_at=0,
        start_date=None,
        finish_date=None,
        group_id=None,
        metadata={},
        tag_names=tag_names,
    )


def _history(
    id: int,
    field: TaskField,
    old: str | None,
    new: str | None,
    source: str = "cli",
) -> JournalEntry:
    return JournalEntry(
        id=id,
        entity_type=EntityType.TASK,
        entity_id=1,
        workspace_id=1,
        field=field,
        old_value=old,
        new_value=new,
        source=source,
        changed_at=0,
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


# ---- format_workspace_list ----


class TestFormatWorkspaceList:
    def test_empty(self):
        assert presenters.format_workspace_list((), None) == "no workspaces"

    def test_active_marker(self):
        workspaces = (_workspace(1, "A"), _workspace(2, "B"))
        out = presenters.format_workspace_list(workspaces, active_id=2)
        assert "  A\n  B *" == out

    def test_archived_marker(self):
        workspaces = (_workspace(1, "A", archived=True),)
        out = presenters.format_workspace_list(workspaces, active_id=None)
        assert "(archived)" in out

    def test_active_and_archived(self):
        workspaces = (_workspace(1, "A", archived=True),)
        out = presenters.format_workspace_list(workspaces, active_id=1)
        assert " *" in out
        assert "(archived)" in out


# ---- format_status_list ----


class TestFormatStatusList:
    def test_empty(self):
        assert presenters.format_status_list(()) == "no statuses"

    def test_shows_name(self):
        statuses = (_status(1, "Todo"), _status(2, "Done"))
        out = presenters.format_status_list(statuses)
        assert "Todo" in out
        assert "Done" in out

    def test_archived_marker(self):
        statuses = (_status(1, "active"), _status(2, "old", archived=True))
        out = presenters.format_status_list(statuses)
        assert "  active" in out
        assert "old (archived)" in out

    def test_no_archived_marker_on_active(self):
        statuses = (_status(1, "active"),)
        out = presenters.format_status_list(statuses)
        assert "(archived)" not in out


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
            id=7,
            workspace_id=1,
            title="T",
            description=None,
            status_id=1,
            priority=2,
            due_date=None,
            position=0,
            archived=False,
            created_at=0,
            start_date=None,
            finish_date=None,
            group_id=None,
            metadata={},
            status=_status(1, "Todo"),
            group=None,
            edge_sources=(),
            edge_targets=(),
            history=(),
            tags=(),
        )
        base.update(overrides)
        return TaskDetail(**base)

    def test_minimal(self):
        out = presenters.format_task_detail(self._detail())
        assert "task-0007  T" in out
        assert "Status:      Todo" in out
        assert "Priority:    2" in out
        # optional fields absent
        assert "Due:" not in out
        assert "Description:" not in out

    def test_with_all_fields(self):
        d = self._detail(
            group=Group(
                id=3,
                workspace_id=1,
                title="g",
                description=None,
                parent_id=None,
                position=0,
                archived=False,
                created_at=0,
                metadata={},
            ),
            tags=(_tag(1, "bug"), _tag(2, "urgent")),
            description="do the thing",
            due_date=1_000_000,
            edge_sources=(EdgeRef(node_type="task", node_id=2, node_title="blocker", kind="blocks"),),
            edge_targets=(EdgeRef(node_type="task", node_id=3, node_title="blocked", kind="related-to"),),
            history=(_history(1, TaskField.TITLE, "old", "T"),),
        )
        out = presenters.format_task_detail(d)
        assert "Group:       g (group-0003)" in out
        assert "Tags:        bug, urgent" in out
        assert "Due:" in out
        assert "Edge sources: task:2 blocker (blocks)" in out
        assert "Edge targets: task:3 blocked (related-to)" in out
        assert "Description:" in out
        assert "do the thing" in out
        assert "History:" in out
        assert "    " in out  # history lines are indented


# ---- format_workspace_list_view ----


class TestFormatWorkspaceListView:
    def test_statuses_with_headers(self):
        view = WorkspaceListView(
            workspace=_workspace(1, "B"),
            statuses=(
                WorkspaceListStatus(status=_status(1, "Todo"), tasks=()),
                WorkspaceListStatus(status=_status(2, "Done"), tasks=()),
            ),
        )
        out = presenters.format_workspace_list_view(view)
        assert "== Todo ==" in out
        assert "== Done ==" in out
        assert "(empty)" in out

    def test_task_rendering(self):
        view = WorkspaceListView(
            workspace=_workspace(1),
            statuses=(
                WorkspaceListStatus(
                    status=_status(1, "Todo"),
                    tasks=(
                        _list_item(1, "do it", priority=3, tag_names=("bug",)),
                    ),
                ),
            ),
        )
        out = presenters.format_workspace_list_view(view)
        assert "task-0001" in out
        assert "[P3]" in out
        assert "do it" in out
        assert "[bug]" in out

    def test_no_tags(self):
        view = WorkspaceListView(
            workspace=_workspace(1),
            statuses=(
                WorkspaceListStatus(
                    status=_status(1, "Todo"),
                    tasks=(_list_item(1, "bare"),),
                ),
            ),
        )
        out = presenters.format_workspace_list_view(view)
        assert "bare" in out
        assert "[bug]" not in out


# ---- format_workspace_context ----


class TestFormatWorkspaceContext:
    def _ctx(self, *, name="dev", tags=(), groups=()) -> WorkspaceContext:
        view = WorkspaceListView(workspace=_workspace(1, name), statuses=())
        return WorkspaceContext(view=view, tags=tags, groups=groups)

    def _ref(self, id: int, title: str) -> GroupRef:
        return GroupRef(
            id=id,
            workspace_id=1,
            title=title,
            description=None,
            parent_id=None,
            position=0,
            archived=False,
            created_at=0,
            metadata={},
        )

    def test_workspace_header(self):
        out = presenters.format_workspace_context(self._ctx(name="work"))
        assert out.startswith("== work ==")

    def test_tags_line(self):
        out = presenters.format_workspace_context(self._ctx(tags=(_tag(1, "bug"),)))
        assert "Tags: bug" in out

    def test_groups_line(self):
        g = self._ref(1, "G1")
        out = presenters.format_workspace_context(self._ctx(groups=(g,)))
        assert "Groups: G1" in out

    def test_no_tags_no_line(self):
        out = presenters.format_workspace_context(self._ctx())
        assert "Tags:" not in out

    def test_no_groups_no_line(self):
        out = presenters.format_workspace_context(self._ctx())
        assert "Groups:" not in out


# ---- format_group_list ----


class TestFormatGroupList:
    def _ref(self, id: int, title: str, *, archived: bool = False, task_count: int = 0) -> GroupRef:
        return GroupRef(
            id=id,
            workspace_id=1,
            title=title,
            description=None,
            parent_id=None,
            position=0,
            archived=archived,
            created_at=0,
            metadata={},
            task_ids=tuple(range(task_count)),
            child_ids=(),
        )

    def test_empty(self):
        assert presenters.format_group_list(()) == "no groups"

    def test_single_group(self):
        out = presenters.format_group_list((self._ref(1, "G", task_count=2),))
        assert "group-0001" in out
        assert "(2 tasks)" in out

    def test_multiple_groups(self):
        out = presenters.format_group_list((self._ref(1, "G1"), self._ref(2, "G2")))
        assert "G1" in out
        assert "G2" in out

    def test_archived_marker(self):
        out = presenters.format_group_list((self._ref(1, "G", archived=True),))
        assert "(archived)" in out


# ---- format_group_detail ----


class TestFormatGroupDetail:
    def test_minimal(self):
        d = GroupDetail(
            id=1,
            workspace_id=1,
            title="G",
            description=None,
            parent_id=None,
            position=0,
            archived=False,
            created_at=0,
            tasks=(),
            children=(),
            parent=None,
            metadata={},
            edge_sources=(),
            edge_targets=(),
        )
        out = presenters.format_group_detail(d, ancestry_titles=("G",))
        assert "group-0001  G" in out
        assert "Path:        G" in out
        assert "Tasks:       0" in out

    def test_description_rendered(self):
        d = GroupDetail(
            id=1,
            workspace_id=1,
            title="G",
            description="Important group",
            parent_id=None,
            position=0,
            archived=False,
            created_at=0,
            tasks=(),
            children=(),
            parent=None,
            metadata={},
            edge_sources=(),
            edge_targets=(),
        )
        out = presenters.format_group_detail(d, ancestry_titles=("G",))
        assert "group-0001  G" in out
        assert "Description: Important group" in out

    def test_no_description_omitted(self):
        d = GroupDetail(
            id=1,
            workspace_id=1,
            title="G",
            description=None,
            parent_id=None,
            position=0,
            archived=False,
            created_at=0,
            tasks=(),
            children=(),
            parent=None,
            metadata={},
            edge_sources=(),
            edge_targets=(),
        )
        out = presenters.format_group_detail(d, ancestry_titles=("G",))
        lines = out.splitlines()
        assert lines[0].startswith("group-0001  G")
        assert lines[1].startswith("  Path:")

    def test_with_children_and_tasks(self):
        child = Group(
            id=2,
            workspace_id=1,
            title="ChildA",
            description=None,
            parent_id=1,
            position=0,
            archived=False,
            created_at=0,
            metadata={},
        )
        d = GroupDetail(
            id=1,
            workspace_id=1,
            title="Root",
            description=None,
            parent_id=None,
            position=0,
            archived=False,
            created_at=0,
            tasks=(_task(10, "work", priority=3, due_date=1_000_000),),
            children=(child,),
            parent=None,
            metadata={},
            edge_sources=(),
            edge_targets=(),
        )
        out = presenters.format_group_detail(d, ancestry_titles=("Root",))
        assert "group-0001  Root" in out
        assert "Sub-groups: ChildA" in out
        assert "task-0010" in out
        assert "[P3]" in out
        assert "work" in out
        assert "due:" in out


# ---- format_move_preview ----


class TestFormatMovePreview:
    def _preview(self, **overrides) -> MoveToWorkspacePreview:
        base = dict(
            task_id=5,
            task_title="T",
            source_workspace_id=1,
            target_workspace_id=2,
            target_status_id=3,
            can_move=True,
            blocking_reason=None,
            edge_endpoints=(),
            is_archived=False,
        )
        base.update(overrides)
        return MoveToWorkspacePreview(**base)

    def test_can_move(self):
        out = presenters.format_move_preview(
            self._preview(), "other", "Backlog", source_workspace_name="dev"
        )
        assert "dry-run" in out
        assert "task-0005" in out
        assert "workspace 'other' / status 'Backlog'" in out
        assert "workspace 'dev'" in out
        assert "transfer OK" in out

    def test_blocked_by_active_edges(self):
        p = self._preview(
            can_move=False,
            edge_endpoints=(("task", 10), ("group", 11)),
        )
        out = presenters.format_move_preview(p, "other", "Backlog", source_workspace_name="dev")
        assert "has active edges: task:10, group:11" in out
        assert "move would FAIL" in out

    def test_blocked_other_reason(self):
        p = self._preview(can_move=False, blocking_reason="task is archived")
        out = presenters.format_move_preview(p, "other", "Backlog", source_workspace_name="dev")
        assert "task is archived" in out
        assert "move would FAIL" in out


class TestFormatArchivePreview:
    def test_already_archived(self):
        p = ArchivePreview(
            entity_type="task",
            entity_name="t",
            already_archived=True,
            task_count=0,
            group_count=0,
            status_count=0,
        )
        assert "already archived" in presenters.format_archive_preview(p)

    def test_no_cascade_targets(self):
        p = ArchivePreview(
            entity_type="task",
            entity_name="t",
            already_archived=False,
            task_count=0,
            group_count=0,
            status_count=0,
        )
        out = presenters.format_archive_preview(p)
        assert "would archive" in out
        assert "tasks:" not in out

    def test_with_descendants(self):
        p = ArchivePreview(
            entity_type="group",
            entity_name="g",
            already_archived=False,
            task_count=3,
            group_count=1,
            status_count=0,
        )
        out = presenters.format_archive_preview(p)
        assert "descendant groups: 1" in out
        assert "tasks: 3" in out

    def test_workspace_full(self):
        p = ArchivePreview(
            entity_type="workspace",
            entity_name="w",
            already_archived=False,
            task_count=5,
            group_count=2,
            status_count=3,
        )
        out = presenters.format_archive_preview(p)
        assert "groups: 2" in out
        assert "statuses: 3" in out
        assert "tasks: 5" in out


class TestFormatTaskDetailMetadata:
    def _detail(self, **overrides) -> TaskDetail:
        base = dict(
            id=7,
            workspace_id=1,
            title="T",
            description=None,
            status_id=1,
            priority=2,
            due_date=None,
            position=0,
            archived=False,
            created_at=0,
            start_date=None,
            finish_date=None,
            group_id=None,
            metadata={},
            status=_status(1, "Todo"),
            group=None,
            edge_sources=(),
            edge_targets=(),
            history=(),
            tags=(),
        )
        base.update(overrides)
        return TaskDetail(**base)

    def test_metadata_shown_when_nonempty(self):
        out = presenters.format_task_detail(
            self._detail(metadata={"branch": "feat/kv", "jira": "PROJ-1"})
        )
        assert "Metadata:" in out
        assert "branch: feat/kv" in out
        assert "jira: PROJ-1" in out

    def test_metadata_hidden_when_empty(self):
        out = presenters.format_task_detail(self._detail())
        assert "Metadata:" not in out
