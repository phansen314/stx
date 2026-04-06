from __future__ import annotations

from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import Footer, Header, Static

from sticky_notes import service
from sticky_notes.active_board import get_active_board_id, set_active_board_id
from sticky_notes.models import Task, TaskFilter
from sticky_notes.tui.widgets.task_card import TaskCard

if TYPE_CHECKING:
    from sticky_notes.tui.app import StickyNotesApp


class AllTasksScreen(Screen):
    BINDINGS = [
        Binding("escape", "go_back", "Back"),
        Binding("n", "create_task", "New Task"),
        Binding("b", "select_board", "Switch Board"),
        Binding("p", "select_project", "Filter Project"),
        Binding("c", "filter_statuses", "Status Filter"),
    ]

    @property
    def typed_app(self) -> StickyNotesApp:
        return self.app  # type: ignore[return-value]

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._board_id: int | None = None
        self._project_filter_id: int | None = None
        self._status_filter_ids: frozenset[int] | None = None
        self._cards: list[TaskCard] = []
        self._card_idx: int = 0

    def compose(self) -> ComposeResult:
        yield Header()
        yield VerticalScroll(id="all-tasks-container")
        yield Footer()

    def on_mount(self) -> None:
        self._load_tasks()

    def _load_tasks(self) -> None:
        conn = self.typed_app.conn
        db_path = self.typed_app.db_path
        config = self.typed_app.config

        self._board_id = get_active_board_id(db_path)
        if self._board_id is None:
            container = self.query_one("#all-tasks-container")
            container.mount(Static("No active board"))
            return

        statuses = service.list_statuses(conn, self._board_id)
        status_map = {s.id: s for s in statuses}
        projects = service.list_projects(conn, self._board_id)
        project_map = {proj.id: proj for proj in projects}

        task_filter = TaskFilter(
            include_archived=config.show_archived,
            project_id=self._project_filter_id,
        )
        tasks = service.list_tasks_filtered(
            conn, self._board_id, task_filter=task_filter
        )

        # Group: project_id -> status_id -> list[Task]
        grouped: dict[int | None, dict[int, list[Task]]] = {}
        for task in tasks:
            proj_group = grouped.setdefault(task.project_id, {})
            status_group = proj_group.setdefault(task.status_id, [])
            status_group.append(task)

        # Sort: named projects alphabetically first, None last
        named_ids = sorted(
            (pid for pid in grouped if pid is not None),
            key=lambda pid: project_map[pid].name.lower(),
        )
        ordered_project_ids: list[int | None] = [*named_ids]
        if None in grouped:
            ordered_project_ids.append(None)

        # Status ordering: config.status_order first (known IDs), then alphabetically
        order = config.status_order
        if order:
            order_map = {sid: i for i, sid in enumerate(order)}
            status_order = sorted(
                status_map.keys(),
                key=lambda sid: (0 if sid in order_map else 1, order_map.get(sid, 0), status_map[sid].name, sid),
            )
        else:
            status_order = sorted(status_map.keys(), key=lambda sid: (status_map[sid].name, sid))
        if self._status_filter_ids is not None:
            status_order = [sid for sid in status_order if sid in self._status_filter_ids]

        widgets: list[Static | TaskCard] = []
        self._cards = []

        for pid in ordered_project_ids:
            proj_name = project_map[pid].name if pid is not None else "No Project"
            widgets.append(
                Static(f"── {proj_name} " + "─" * max(0, 40 - len(proj_name)),
                       classes="project-group-header")
            )
            status_groups = grouped[pid]
            for sid in status_order:
                if sid not in status_groups:
                    continue
                status_tasks = status_groups[sid]
                status_name = status_map[sid].name
                widgets.append(
                    Static(f"  {status_name} ({len(status_tasks)})",
                           classes="column-sub-header")
                )
                for task in status_tasks:
                    card = TaskCard(task)
                    widgets.append(card)
                    self._cards.append(card)

        container = self.query_one("#all-tasks-container")
        if widgets:
            container.mount(*widgets)

        self._card_idx = 0
        if self._cards:
            self.call_after_refresh(self._focus_current)

    def _focus_current(self) -> None:
        if not self._cards:
            return
        self._card_idx = min(self._card_idx, len(self._cards) - 1)
        self._cards[self._card_idx].focus()

    def _focus_card_by_id(self, task_id: int) -> None:
        for idx, card in enumerate(self._cards):
            if card.task_data.id == task_id:
                self._card_idx = idx
                self._focus_current()
                return
        self._focus_current()

    async def reload(self, focus_task_id: int | None = None) -> None:
        container = self.query_one("#all-tasks-container")
        await container.remove_children()
        self._cards = []
        self._load_tasks()
        if focus_task_id is not None:
            self.call_after_refresh(lambda: self._focus_card_by_id(focus_task_id))

    # ---- Navigation ----

    def on_task_card_navigate(self, message: TaskCard.Navigate) -> None:
        message.stop()
        if message.direction == "up":
            if self._card_idx > 0:
                self._card_idx -= 1
                self._focus_current()
        elif message.direction == "down":
            if self._card_idx < len(self._cards) - 1:
                self._card_idx += 1
                self._focus_current()
        # left/right ignored in flat list

    def on_task_card_move_request(self, message: TaskCard.MoveRequest) -> None:
        message.stop()  # No column movement in all-tasks view

    # ---- CRUD handlers (same patterns as BoardView) ----

    def on_task_card_show_request(self, message: TaskCard.ShowRequest) -> None:
        message.stop()
        from sticky_notes.tui.screens.task_detail import TaskDetailModal

        self.typed_app.push_screen(
            TaskDetailModal(message.task_id),
            callback=self._handle_detail_dismiss,
        )

    def _handle_detail_dismiss(self, result: int | None) -> None:
        if result is not None:
            self._open_edit(result)

    def on_task_card_edit_request(self, message: TaskCard.EditRequest) -> None:
        message.stop()
        self._open_edit(message.task_id)

    def _open_edit(self, task_id: int) -> None:
        from sticky_notes.tui.screens.task_form import TaskFormModal

        task = service.get_task(self.typed_app.conn, task_id)
        defaults = {
            "title": task.title,
            "description": task.description,
            "priority": task.priority,
            "due_date": task.due_date,
            "project_id": task.project_id,
        }
        self.typed_app.push_screen(
            TaskFormModal(
                self.typed_app.conn,
                self._board_id,
                mode="edit",
                defaults=defaults,
                default_priority=self.typed_app.config.default_priority,
            ),
            callback=lambda r, tid=task_id: self._handle_edit(tid, r),
        )

    def _handle_edit(self, task_id: int, result: dict | None) -> None:
        if result is None:
            return
        task = service.get_task(self.typed_app.conn, task_id)
        current = {
            "title": task.title,
            "description": task.description,
            "priority": task.priority,
            "due_date": task.due_date,
            "project_id": task.project_id,
        }
        changes = {k: v for k, v in result.items() if current.get(k) != v}
        if changes:
            service.update_task(self.typed_app.conn, task_id, changes, "tui")
        self.run_worker(self.reload(focus_task_id=task_id))

    def on_task_card_archive_request(self, message: TaskCard.ArchiveRequest) -> None:
        message.stop()
        task_id = message.task_id
        if self.typed_app.config.confirm_archive:
            from sticky_notes.tui.screens.confirm_dialog import ConfirmDialog

            self.typed_app.push_screen(
                ConfirmDialog(f"Archive task-{task_id:04d}?"),
                callback=lambda ok, tid=task_id: self._handle_archive_confirm(tid, ok),
            )
        else:
            self.run_worker(self._archive_and_reload(task_id))

    def _handle_archive_confirm(self, task_id: int, confirmed: bool) -> None:
        if confirmed:
            self.run_worker(self._archive_and_reload(task_id))

    async def _archive_and_reload(self, task_id: int) -> None:
        service.update_task(self.typed_app.conn, task_id, {"archived": True}, "tui")
        remaining = [c for c in self._cards if c.task_data.id != task_id]
        if remaining:
            idx = min(self._card_idx, len(remaining) - 1)
            await self.reload(focus_task_id=remaining[idx].task.id)
        else:
            await self.reload()

    # ---- Action handlers ----

    def action_go_back(self) -> None:
        self.app.pop_screen()
        # Trigger board view reload to reflect any mutations
        from sticky_notes.tui.widgets.board_view import BoardView

        try:
            board_view = self.app.query_one(BoardView)
            board_view.run_worker(board_view.reload())
        except Exception:
            pass

    def action_create_task(self) -> None:
        if self._board_id is None:
            return
        from sticky_notes.tui.screens.task_form import TaskFormModal

        # Default status: use focused card's status, or first status
        statuses = service.list_statuses(self.typed_app.conn, self._board_id)
        if not statuses:
            return
        if self._cards and self._card_idx < len(self._cards):
            status_id = self._cards[self._card_idx].task_data.status_id
        else:
            status_id = statuses[0].id

        self.typed_app.push_screen(
            TaskFormModal(
                self.typed_app.conn,
                self._board_id,
                mode="create",
                status_id=status_id,
                default_priority=self.typed_app.config.default_priority,
            ),
            callback=self._handle_create,
        )

    def _handle_create(self, result: dict | None) -> None:
        if result is None:
            return
        task = service.create_task(
            self.typed_app.conn,
            board_id=self._board_id,
            title=result["title"],
            status_id=result["status_id"],
            description=result.get("description"),
            priority=result.get("priority", 1),
            due_date=result.get("due_date"),
            project_id=result.get("project_id"),
        )
        self.run_worker(self.reload(focus_task_id=task.id))

    def action_select_board(self) -> None:
        from sticky_notes.tui.screens.board_select import BoardSelectModal

        self.typed_app.push_screen(
            BoardSelectModal(self.typed_app.conn, self._board_id),
            callback=self._handle_board_select,
        )

    def _handle_board_select(self, result: int | None) -> None:
        if result is None or result == self._board_id:
            return
        set_active_board_id(self.typed_app.db_path, result)
        self._project_filter_id = None
        self._status_filter_ids = None
        self.run_worker(self.reload())

    def action_select_project(self) -> None:
        if self._board_id is None:
            return
        from sticky_notes.tui.screens.project_select import (
            ProjectSelectModal,
            _CANCEL_SENTINEL,
        )

        self._cancel_sentinel = _CANCEL_SENTINEL
        self.typed_app.push_screen(
            ProjectSelectModal(
                self.typed_app.conn,
                self._board_id,
                self._project_filter_id,
            ),
            callback=self._handle_project_select,
        )

    def _handle_project_select(self, result: int) -> None:
        if result == self._cancel_sentinel:
            return
        new_filter = result if result != 0 else None
        if new_filter == self._project_filter_id:
            return
        self._project_filter_id = new_filter
        self.run_worker(self.reload())

    def action_filter_statuses(self) -> None:
        if self._board_id is None:
            return
        from sticky_notes.tui.screens.status_filter import StatusFilterModal

        statuses = service.list_statuses(self.typed_app.conn, self._board_id)
        self.typed_app.push_screen(
            StatusFilterModal(statuses, self._status_filter_ids),
            callback=self._handle_status_filter,
        )

    def _handle_status_filter(self, result: frozenset[int] | None) -> None:
        if result is None:
            return
        # If all statuses selected, reset to None (show all)
        statuses = service.list_statuses(self.typed_app.conn, self._board_id)
        all_ids = frozenset(s.id for s in statuses)
        new_filter = None if result == all_ids else result
        if new_filter == self._status_filter_ids:
            return
        self._status_filter_ids = new_filter
        self.run_worker(self.reload())
