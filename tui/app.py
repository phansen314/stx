"""StxApp — Textual TUI over the stx daemon. Tree (workspace→track→segment→task) on the left,
a per-track kanban on the right. Keybindings mirror the old TUI so muscle memory transfers.

Network is a daemon over HTTP, not in-process SQLite, so every daemon call is pushed off the
Textual event loop with ``asyncio.to_thread`` — the UI never blocks on I/O. Reads that fan out
(the full reload) run concurrently on a small thread pool. Because ``requests.Session`` is not
safe to share across threads, every offloaded call goes through a *thread-local* Client
(``_client_for``): concurrent calls land on different threads, each with its own session, so no
session is ever touched by two threads at once.

Freshness is poll-based: a timer hits ``GET /changes`` (a cheap monotonic token the daemon bumps
on every committed write) and reloads only when the token moves — so changes from other writers
(CLI, sub-agents, other sessions) surface within a couple of seconds. The same poll loop is the
reconnect heartbeat: a dead/restarting daemon degrades to a single "unreachable" notice instead
of a crash, and recovery triggers an automatic reload.
"""
from __future__ import annotations

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import NamedTuple

from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.widgets import Footer, Header

from stxc import Client, StxConnError, StxError
from stxc.models import Segment, Task, Track, Workspace, build
from .config import load_config, save_config
from .screens import (
    ConfigModal, ConfirmModal, EdgeModal, EntityEditModal, MetadataModal, NameModal,
    NewResourceModal, RegistryModal, TaskForm,
)
from .widgets import KanbanBoard, KanbanColumn, TaskCard, TrackBlock, WorkspaceTree, WsBlock

REFRESH_SECS = 2.0  # default seed (see tui/config.py DEFAULTS); actual cadence comes from config
_FETCH_POOL_WORKERS = 8

# Thread-local Clients: requests.Session is not safe to share across threads, so each worker
# thread gets its own. Concurrent offloaded calls run on distinct threads → distinct sessions.
_tls = threading.local()


def _client_for(base_url: str) -> Client:
    c = getattr(_tls, "client", None)
    if c is None or c.base != base_url.rstrip("/"):
        c = Client(base_url)
        _tls.client = c
    return c


class _Snapshot(NamedTuple):
    blocks: list[WsBlock]
    statuses: dict[int, list]
    kinds: dict[int, list]
    transitions: dict[int, list]


def _fetch_snapshot(base_url: str) -> _Snapshot:
    """Blocking; runs in a worker thread. Fetch every workspace, then — concurrently — each
    workspace's registries + tracks, then each track's segments + tasks. Wall-time collapses from
    O(workspaces+tracks) serial round-trips to a couple of pooled batches. Any daemon failure
    propagates (StxError) to the caller's ``except StxError``."""
    root = _client_for(base_url)
    workspaces = root.list_workspaces()
    with ThreadPoolExecutor(max_workers=_FETCH_POOL_WORKERS, thread_name_prefix="stx-fetch") as pool:
        def load_ws(ws):
            c = _client_for(base_url)
            return (ws, c.statuses(ws.id), c.kinds(ws.id), c.transitions(ws.id), c.tracks(ws.id))

        ws_rows = list(pool.map(load_ws, workspaces))  # list() forces completion / re-raises

        def load_track(item):
            ws_id, tr = item
            c = _client_for(base_url)
            return (tr.id, c.segments(tr.id), c.track_tasks(tr.id))

        pairs = [(ws.id, tr) for ws, _s, _k, _t, tracks in ws_rows for tr in tracks]
        track_rows = list(pool.map(load_track, pairs))

    seg_tasks = {tid: (segs, tasks) for tid, segs, tasks in track_rows}
    statuses, kinds, transitions, blocks = {}, {}, {}, []
    for ws, s, k, t, tracks in ws_rows:
        statuses[ws.id], kinds[ws.id], transitions[ws.id] = s, k, t
        tbs = [TrackBlock(tr, *seg_tasks[tr.id]) for tr in tracks]
        blocks.append(WsBlock(ws, tbs))
    return _Snapshot(blocks, statuses, kinds, transitions)


class StxApp(App):
    CSS_PATH = "stx.tcss"
    TITLE = "\U0001f4cc stx \U0001f4cc"
    BINDINGS = [
        Binding("w", "focus_tree", "Workspace", show=True),
        Binding("b", "focus_kanban", "Board", show=True),
        Binding("r", "refresh", "Refresh", show=True),
        Binding("e", "edit", "Edit", show=True),
        Binding("a", "archive", "Archive", show=True),
        Binding("n", "new", "New", show=True),
        Binding("d", "edges", "Edges", show=True),
        Binding("g", "registry", "Registry", show=True),
        Binding("m", "metadata", "Metadata", show=True),
        Binding("c", "config", "Config", show=True),
        Binding("f", "toggle_next", "Ready", show=True),
        Binding("[", "status_left", "◀ Status", show=False),
        Binding("]", "status_right", "Status ▶", show=False),
        Binding("shift+left", "status_left", show=False),
        Binding("shift+right", "status_right", show=False),
        Binding("ctrl+q", "quit", "Quit", show=True),
    ]

    def __init__(self, base_url: str = "http://127.0.0.1:8420"):
        super().__init__()
        self._base = base_url.rstrip("/")
        self.active_track: Track | None = None
        self.active_ws_id: int | None = None
        self.active_panel = "tree"
        self._next_only = False
        self._last_focused: TaskCard | KanbanColumn | None = None
        self._statuses: dict[int, list] = {}
        self._kinds: dict[int, list] = {}
        self._transitions: dict[int, list] = {}
        self._ws_tasks: dict[int, list[Task]] = {}  # workspace id → all its live tasks (edge picker)
        self._track_roots: dict[int, int] = {}  # track id → its root segment id (new-segment parent)
        # freshness / connection state
        self._last_seq: int | None = None
        self._connected = True
        self._refresh_pending = False
        # local preferences (theme + poll cadence); see tui/config.py
        self._cfg = load_config()
        self._refresh_secs: float = self._cfg["refresh_secs"]
        self._refresh_timer = None

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="main-panels"):
            with Vertical(id="workspaces-panel"):
                yield WorkspaceTree("Workspaces", id="workspaces-tree")
            with Vertical(id="kanban-panel"):
                yield KanbanBoard(id="kanban-columns")
        yield Footer()

    async def on_mount(self) -> None:
        if self._cfg["theme"] in self.available_themes:
            self.theme = self._cfg["theme"]  # guard a theme dropped by a Textual upgrade
        await self.reload()
        self.query_one(WorkspaceTree).focus()
        # Seed the change token now so the very first external write after startup is detected —
        # otherwise the first poll would only seed _last_seq and silently miss that change.
        try:
            self._last_seq, _ = await asyncio.to_thread(lambda: _client_for(self._base).changes())
        except StxError:
            pass
        self._refresh_timer = self.set_interval(self._refresh_secs, self._poll)

    # ── data load ──
    async def reload(self) -> None:
        try:
            snap = await asyncio.to_thread(_fetch_snapshot, self._base)
        except StxError as e:
            self._note_error(e)
            return
        self._mark_connected()
        self._statuses, self._kinds, self._transitions = snap.statuses, snap.kinds, snap.transitions
        self._ws_tasks = {b.workspace.id: [t for tb in b.tracks for t in tb.tasks] for b in snap.blocks}
        self._track_roots = {
            tb.track.id: root.id
            for b in snap.blocks for tb in b.tracks
            if (root := next((s for s in tb.segments if s.is_root), None)) is not None
        }
        self.query_one(WorkspaceTree).load(snap.blocks, expand_workspace_id=self.active_ws_id)
        tracks = [tb.track for b in snap.blocks for tb in b.tracks]
        if self.active_track is not None:
            self.active_track = next((t for t in tracks if t.id == self.active_track.id), None)
        if self.active_track is None and tracks:
            self.active_track = tracks[0]
        # Reuse the tasks already gathered in the snapshot for the active track (dedupes the old
        # second track_tasks fetch); the ready-only filter still needs its own /next call.
        active_tasks: list[Task] = []
        if self.active_track is not None:
            active_tasks = next(
                (tb.tasks for b in snap.blocks for tb in b.tracks if tb.track.id == self.active_track.id),
                [],
            )
        await self._render_board(active_tasks)

    async def _reload_board(self) -> None:
        track = self.active_track
        if track is None:
            await self.query_one(KanbanBoard).remove_children()
            return
        try:
            tasks = await asyncio.to_thread(lambda: _client_for(self._base).track_tasks(track.id))
        except StxError as e:
            self._note_error(e)
            return
        self._mark_connected()
        await self._render_board(tasks)

    async def _render_board(self, tasks: list[Task]) -> None:
        kanban = self.query_one(KanbanBoard)
        track = self.active_track
        if track is None:
            await kanban.remove_children()
            return
        ws = track.workspace_id
        self.active_ws_id = ws
        if self._next_only:
            try:
                ready = await asyncio.to_thread(
                    lambda: {i["id"] for i in _client_for(self._base).next(ws, track=track.id)}
                )
            except StxError as e:
                self._note_error(e)
                return
            tasks = [t for t in tasks if t.id in ready]
        await kanban.load(self._statuses.get(ws, []), tasks)
        self._restore_focus()

    def _restore_focus(self) -> None:
        """After a board reload, put focus back where it was — matched by id, with fallbacks —
        so status moves, manual refresh, and auto-refresh all keep the user's place (mirrors the
        old TUI's central restore). Only acts on the board; the tree keeps its own cursor, and we
        never steal focus while a modal is open."""
        if self.active_panel != "kanban" or len(self.screen_stack) > 1:
            return
        last = self._last_focused
        board = self.query_one(KanbanBoard)
        if isinstance(last, KanbanColumn):
            try:
                col = board.query_one(f"#status-col-{last.status_id}", KanbanColumn)
                self.set_focus(col)
                self._last_focused = col
                return
            except NoMatches:
                pass
        elif isinstance(last, TaskCard):
            for card in board.query(TaskCard):
                if card.task_data.id == last.task_data.id:
                    self.set_focus(card)
                    self._last_focused = card
                    return
        cards = board.query(TaskCard)
        if cards:
            first = cards.first()
            self.set_focus(first)
            self._last_focused = first

    def _trigger_reload(self) -> None:
        self._refresh_pending = False
        self.run_worker(self.reload(), exclusive=True, group="load")

    def _trigger_board(self) -> None:
        self.run_worker(self._reload_board(), exclusive=True, group="load")

    # ── freshness / connection ──
    def _poll(self) -> None:
        self.run_worker(self._poll_once(), exclusive=True, group="poll")

    async def _poll_once(self) -> None:
        try:
            seq, _schema = await asyncio.to_thread(lambda: _client_for(self._base).changes())
        except StxConnError as e:
            self._note_error(e)
            return
        except StxError:
            return  # a transient API error on the token is not worth surfacing; try again next tick
        recovered = not self._connected
        self._mark_connected()
        # A refresh deferred while a modal was open lands once the modal has closed.
        if self._refresh_pending and len(self.screen_stack) == 1:
            self._trigger_reload()
        elif recovered or (self._last_seq is not None and seq != self._last_seq):
            self._refresh_or_defer()
        self._last_seq = seq

    def _refresh_or_defer(self) -> None:
        # Don't yank data out from under an in-progress edit; reload once the modal closes.
        if len(self.screen_stack) > 1:
            self._refresh_pending = True
        else:
            self._trigger_reload()

    def _note_error(self, e: StxError) -> None:
        if isinstance(e, StxConnError):
            if self._connected:
                self._connected = False
                self.notify("daemon unreachable — retrying…", severity="error", timeout=6)
        else:
            self.notify(self._explain(e), severity="warning")

    def _mark_connected(self) -> None:
        if not self._connected:
            self._connected = True
            self.notify("daemon reconnected", severity="information")

    # ── focus tracking ──
    def on_descendant_focus(self, event: events.DescendantFocus) -> None:
        w = event.widget
        if isinstance(w, WorkspaceTree):
            self.active_panel = "tree"
        elif isinstance(w, (TaskCard, KanbanColumn)):
            self.active_panel = "kanban"
            self._last_focused = w

    # ── tree / board messages ──
    def on_workspace_tree_track_selected(self, event: WorkspaceTree.TrackSelected) -> None:
        if self.active_track is not None and event.track.id == self.active_track.id:
            return
        self.active_track = event.track
        self.active_ws_id = event.track.workspace_id
        self._trigger_board()

    def on_workspace_tree_task_selected(self, event: WorkspaceTree.TaskSelected) -> None:
        self._edit_task(event.task)

    def on_kanban_board_task_activated(self, event: KanbanBoard.TaskActivated) -> None:
        self._edit_task(event.task)

    async def on_kanban_board_task_status_move(self, event: KanbanBoard.TaskStatusMove) -> None:
        task, to = event.task, event.new_status_id
        ws = task.workspace_id
        legal = any(
            tr.from_status_id == task.status_id and tr.to_status_id == to
            for tr in self._transitions.get(ws, [])
        )
        if not legal:
            self.notify("illegal status move (no transition)", severity="warning")
            return
        try:
            await asyncio.to_thread(
                lambda: _client_for(self._base).move_status(task.id, to, task.version)
            )
        except StxError as e:
            self.notify(self._explain(e), severity="warning")
            self._trigger_reload()
            return
        self._trigger_board()

    # ── actions ──
    def action_focus_tree(self) -> None:
        self.set_focus(self.query_one(WorkspaceTree))

    def action_focus_kanban(self) -> None:
        cards = self.query(TaskCard)
        if cards:
            self.set_focus(cards.first())

    def action_refresh(self) -> None:
        self._trigger_reload()

    def action_toggle_next(self) -> None:
        self._next_only = not self._next_only
        self.notify("ready-only" if self._next_only else "all tasks")
        self._trigger_board()

    def action_status_left(self) -> None:
        self.query_one(KanbanBoard)._move_status(-1)

    def action_status_right(self) -> None:
        self.query_one(KanbanBoard)._move_status(1)

    def _focused_task(self) -> Task | None:
        if self.active_panel == "kanban" and isinstance(self.focused, TaskCard):
            return self.focused.task_data
        node = self.query_one(WorkspaceTree).cursor_node
        if node is not None and isinstance(node.data, Task):
            return node.data
        return None

    def _focused_entity(self):
        """The focused Task/Track/Segment/Workspace (or None): the kanban card if the board is
        active, else the tree cursor's node data."""
        if self.active_panel == "kanban" and isinstance(self.focused, TaskCard):
            return self.focused.task_data
        node = self.query_one(WorkspaceTree).cursor_node
        return node.data if node is not None else None

    def action_edit(self) -> None:
        ent = self._focused_entity()
        if isinstance(ent, Task):
            self._edit_task(ent)
        elif isinstance(ent, Track):
            self._edit_track(ent)
        elif isinstance(ent, Workspace):
            self._edit_workspace(ent)
        elif isinstance(ent, Segment):
            self.notify("segments can't be renamed", severity="warning")

    def action_archive(self) -> None:
        if self.active_panel == "kanban" and isinstance(self.focused, TaskCard):
            t = self.focused.task_data
            self._confirm_archive("tasks", t.id, t.title)
            return
        node = self.query_one(WorkspaceTree).cursor_node
        if node is None or node.data is None:
            return
        d = node.data
        if isinstance(d, Task):
            self._confirm_archive("tasks", d.id, d.title)
        elif isinstance(d, Segment):
            self._confirm_archive("segments", d.id, d.name)
        elif isinstance(d, Track):
            self._confirm_archive("tracks", d.id, d.name)

    def action_edges(self) -> None:
        task = self._focused_task()
        if task is not None:
            self.run_worker(self._open_edges(task), group="modal")

    def action_registry(self) -> None:
        ws_id = self._focused_ws_id()
        if ws_id is None:
            self.notify("select a workspace first", severity="warning")
            return
        self._open_registry(ws_id)

    def action_metadata(self) -> None:
        ent = self._focused_entity()
        if isinstance(ent, (Task, Track, Workspace)):
            self._edit_metadata(ent)
        elif isinstance(ent, Segment):
            self.notify("segments have no metadata", severity="warning")

    def action_config(self) -> None:
        self.push_screen(
            ConfigModal(self.theme, sorted(self.available_themes), self._refresh_secs),
            callback=self._on_config_saved,
        )

    def _on_config_saved(self, result: dict | None) -> None:
        if not result:
            return  # cancel already reverted the live theme preview
        self.theme = result["theme"]
        if result["refresh_secs"] != self._refresh_secs:
            self._refresh_secs = result["refresh_secs"]
            if self._refresh_timer is not None:
                self._refresh_timer.stop()
            self._refresh_timer = self.set_interval(self._refresh_secs, self._poll)
        save_config({"theme": self.theme, "refresh_secs": self._refresh_secs})

    def _edit_metadata(self, ent) -> None:
        self.push_screen(
            MetadataModal(f"Metadata — {type(ent).__name__.lower()}", ent.metadata_json),
            callback=lambda s: self._on_metadata_saved(ent, s),
        )

    def _on_metadata_saved(self, ent, meta_json: str | None) -> None:
        if meta_json is None:
            return
        self.run_worker(self._save_metadata(ent, meta_json), group="write")

    async def _save_metadata(self, ent, meta_json: str) -> None:
        def call() -> None:
            c = _client_for(self._base)
            if isinstance(ent, Task):
                c.edit_task(ent.id, ent.version, metadata_json=meta_json)
            elif isinstance(ent, Track):
                c.edit_track(ent.id, ent.version, metadata_json=meta_json)
            elif isinstance(ent, Workspace):
                c.edit_workspace(ent.id, ent.version, metadata_json=meta_json)

        try:
            await asyncio.to_thread(call)
        except StxError as e:
            self.notify(self._explain(e), severity="warning")
        self._trigger_reload()

    def _focused_ws_id(self) -> int | None:
        ent = self._focused_entity()
        if isinstance(ent, Workspace):
            return ent.id
        if isinstance(ent, (Track, Segment, Task)):
            return ent.workspace_id
        return self.active_ws_id

    def action_new(self) -> None:
        self.push_screen(NewResourceModal(), callback=self._on_new_resource)

    # ── modal flows ──
    def _edit_task(self, task: Task) -> None:
        self.run_worker(self._open_task_editor(task), group="modal")

    async def _open_task_editor(self, task: Task) -> None:
        ws = task.workspace_id
        try:
            detail = await asyncio.to_thread(lambda: _client_for(self._base).task_detail(task.id))
        except StxError as e:
            self._note_error(e)
            return
        fresh = build(Task, detail["task"])
        self.push_screen(
            TaskForm(self._statuses.get(ws, []), self._kinds.get(ws, []), fresh),
            callback=self._on_task_saved,
        )

    # ── edge flow ──
    async def _open_edges(self, task: Task) -> None:
        try:
            detail = await asyncio.to_thread(lambda: _client_for(self._base).task_detail(task.id))
        except StxError as e:
            self._note_error(e)
            return
        ws_tasks = [t for t in self._ws_tasks.get(task.workspace_id, []) if t.id != task.id]
        self.push_screen(EdgeModal(task, detail, ws_tasks), callback=lambda op: self._on_edge_op(task, op))

    def _on_edge_op(self, task: Task, op: dict | None) -> None:
        if not op:
            return
        self.run_worker(self._apply_edge(task, op), group="write")

    async def _apply_edge(self, task: Task, op: dict) -> None:
        def call() -> None:
            c = _client_for(self._base)
            kind = op["op"]
            if kind == "add_blocks":
                c.add_blocks(op["source"], op["target"])
            elif kind == "remove_blocks":
                c.remove_blocks(op["source"], op["target"])
            elif kind == "add_relates":
                c.add_relates(op["kind"], op["source"], op["target"])
            elif kind == "remove_relates":
                c.remove_relates(op["kind"], op["source"], op["target"])

        try:
            await asyncio.to_thread(call)
        except StxError as e:
            self.notify(self._explain(e), severity="warning")
        self._trigger_reload()
        await self._open_edges(task)  # re-open with fresh detail so edits chain

    # ── registry flow ──
    def _open_registry(self, ws_id: int) -> None:
        statuses = self._statuses.get(ws_id, [])
        names = {s.id: s.name for s in statuses}
        self.push_screen(
            RegistryModal(statuses, self._kinds.get(ws_id, []), self._transitions.get(ws_id, []), names),
            callback=lambda op: self._on_registry_op(ws_id, op),
        )

    def _on_registry_op(self, ws_id: int, op: dict | None) -> None:
        if not op:
            return
        self.run_worker(self._apply_registry(ws_id, op), group="write")

    async def _apply_registry(self, ws_id: int, op: dict) -> None:
        def call() -> None:
            c = _client_for(self._base)
            kind = op["op"]
            if kind == "add_status":
                c.create_status(ws_id, op["name"], op["kanban_order"], op["terminal"])
            elif kind == "set_default":
                c.set_default_status(ws_id, op["status_id"])
            elif kind == "archive_status":
                c.archive_status(ws_id, op["status_id"])
            elif kind == "add_kind":
                c.create_kind(ws_id, op["name"])
            elif kind == "archive_kind":
                c.archive_kind(ws_id, op["kind_id"])
            elif kind == "add_transition":
                c.create_transition(ws_id, op["from"], op["to"])

        try:
            await asyncio.to_thread(call)
        except StxError as e:
            self.notify(self._explain(e), severity="warning")
        await self.reload()          # refresh the registry caches before reopening
        self._open_registry(ws_id)   # re-open with fresh data so edits chain

    def _on_new_resource(self, choice: str | None) -> None:
        if choice == "task":
            if self.active_track is None:
                self.notify("select a track first", severity="warning")
                return
            ws = self.active_track.workspace_id
            self.push_screen(
                TaskForm(self._statuses.get(ws, []), self._kinds.get(ws, [])),
                callback=self._on_task_saved,
            )
        elif choice == "segment":
            track_id, parent_seg = self._segment_context()
            if track_id is None:
                self.notify("select a track or segment first", severity="warning")
                return
            self.push_screen(
                NameModal("New segment", "Name"),
                callback=lambda name: self._on_new_segment(track_id, parent_seg, name),
            )
        elif choice == "track":
            if self.active_ws_id is None:
                self.notify("create a workspace first", severity="warning")
                return
            self.push_screen(NameModal("New track", "Name"), callback=self._on_new_track)
        elif choice == "workspace":
            self.push_screen(NameModal("New workspace", "Name"), callback=self._on_new_workspace)

    @staticmethod
    def _segment_target(
        data, active_track: Track | None, track_roots: dict[int, int]
    ) -> tuple[int | None, int | None]:
        """Resolve (track_id, parent_segment_id) for a new segment from the focused tree node:
        on a segment → child of it; on a track (or the active-track fallback) → under that track's
        root segment. Parent is the root segment's id (not None) so the new segment renders as a
        child of the track in the tree (WorkspaceTree keys children by the root segment id)."""
        if isinstance(data, Segment):
            return data.track_id, data.id
        track_id = data.id if isinstance(data, Track) else (active_track.id if active_track else None)
        if track_id is None:
            return None, None
        return track_id, track_roots.get(track_id)

    def _segment_context(self) -> tuple[int | None, int | None]:
        node = self.query_one(WorkspaceTree).cursor_node
        data = node.data if node is not None else None
        return self._segment_target(data, self.active_track, self._track_roots)

    def _on_task_saved(self, result: dict | None) -> None:
        if not result:
            return
        self.run_worker(self._save_task(result), group="write")

    async def _save_task(self, result: dict) -> None:
        def do_save() -> None:
            c = _client_for(self._base)
            if result["mode"] == "create":
                c.create_task(
                    track=self.active_track.id, title=result["title"],
                    description=result["description"], priority=result["priority"],
                    status_id=result["status_id"], kind_id=result["kind_id"],
                )
            else:
                changes: dict = {
                    "title": result["title"],
                    "description": result["description"],
                    "priority": result["priority"],
                }
                if result["kind_id"] is None:
                    changes["clearKind"] = True
                else:
                    changes["kindId"] = result["kind_id"]
                c.edit_task(result["task_id"], result["expected_version"], **changes)

        try:
            await asyncio.to_thread(do_save)
        except StxError as e:
            self.notify(self._explain(e), severity="warning")
        self._trigger_reload()

    def _on_new_track(self, name: str | None) -> None:
        if not name:
            return
        self.run_worker(self._create_track(name), group="write")

    async def _create_track(self, name: str) -> None:
        try:
            await asyncio.to_thread(lambda: _client_for(self._base).create_track(self.active_ws_id, name))
        except StxError as e:
            self.notify(self._explain(e), severity="warning")
        self._trigger_reload()

    def _edit_track(self, track: Track) -> None:
        self.push_screen(
            EntityEditModal("Edit track", track.name, track.description),
            callback=lambda r: self._on_track_edited(track, r),
        )

    def _on_track_edited(self, track: Track, result: dict | None) -> None:
        if not result:
            return
        self.run_worker(self._save_track_edit(track, result), group="write")

    async def _save_track_edit(self, track: Track, result: dict) -> None:
        try:
            await asyncio.to_thread(lambda: _client_for(self._base).edit_track(
                track.id, track.version, name=result["name"], description=result["description"]))
        except StxError as e:
            self.notify(self._explain(e), severity="warning")
        self._trigger_reload()

    def _edit_workspace(self, ws: Workspace) -> None:
        self.push_screen(
            EntityEditModal("Edit workspace", ws.name),
            callback=lambda r: self._on_workspace_edited(ws, r),
        )

    def _on_workspace_edited(self, ws: Workspace, result: dict | None) -> None:
        if not result:
            return
        self.run_worker(self._save_workspace_edit(ws, result), group="write")

    async def _save_workspace_edit(self, ws: Workspace, result: dict) -> None:
        try:
            await asyncio.to_thread(lambda: _client_for(self._base).edit_workspace(
                ws.id, ws.version, name=result["name"]))
        except StxError as e:
            self.notify(self._explain(e), severity="warning")
        self._trigger_reload()

    def _on_new_segment(self, track_id: int, parent_seg: int | None, name: str | None) -> None:
        if not name:
            return
        self.run_worker(self._create_segment(track_id, parent_seg, name), group="write")

    async def _create_segment(self, track_id: int, parent_seg: int | None, name: str) -> None:
        try:
            await asyncio.to_thread(
                lambda: _client_for(self._base).create_segment(track_id, name, parent_seg)
            )
        except StxError as e:
            self.notify(self._explain(e), severity="warning")
        self._trigger_reload()

    def _on_new_workspace(self, name: str | None) -> None:
        if not name:
            return
        self.run_worker(self._create_workspace(name), group="write")

    async def _create_workspace(self, name: str) -> None:
        try:
            ws = await asyncio.to_thread(lambda: _client_for(self._base).create_workspace(name))
            self.active_ws_id = ws.id
            self.active_track = None
        except StxError as e:
            self.notify(self._explain(e), severity="warning")
        self._trigger_reload()

    def _confirm_archive(self, kind: str, entity_id: int, label: str) -> None:
        self.push_screen(
            ConfirmModal(f"Archive {kind[:-1]} '{label}'?"),
            callback=lambda yes: self._do_archive(kind, entity_id, yes),
        )

    def _do_archive(self, kind: str, entity_id: int, confirmed: bool | None) -> None:
        if not confirmed:
            return
        self.run_worker(self._archive(kind, entity_id), group="write")

    async def _archive(self, kind: str, entity_id: int) -> None:
        try:
            await asyncio.to_thread(lambda: _client_for(self._base).archive(kind, entity_id))
        except StxError as e:
            self.notify(self._explain(e), severity="warning")
        self._trigger_reload()

    @staticmethod
    def _explain(e: StxError) -> str:
        if isinstance(e, StxConnError):
            return "daemon unreachable"
        friendly = {
            "VersionConflict": "changed elsewhere — refreshing",
            "CycleRejected": "would create a blocks cycle",
            "Duplicate": "edge already exists",
            "CrossWorkspace": "tasks are in different workspaces",
            "NotFound": "edge no longer exists — refreshing",
        }
        return friendly.get(getattr(e, "variant", None), str(e))
