"""Left-hand navigation tree — adapted from the old TUI to the new 4-tier model:
workspace → track → segment(nestable) → task. The synthetic root segment is hidden; its tasks
hang directly under the track. Highlighting a track posts TrackSelected so the app loads its board."""
from __future__ import annotations

from dataclasses import dataclass, field

from textual import events
from textual.message import Message
from textual.widgets import Tree

from ..markup import escape_markup
from stxc.models import Segment, Task, Track, Workspace


@dataclass
class TrackBlock:
    track: Track
    segments: list[Segment] = field(default_factory=list)
    tasks: list[Task] = field(default_factory=list)


@dataclass
class WsBlock:
    workspace: Workspace
    tracks: list[TrackBlock] = field(default_factory=list)


_Node = Workspace | Track | Segment | Task


class WorkspaceTree(Tree[_Node]):
    ICON_WS = "\U0001f4e6"
    ICON_TRACK = "\U0001f686"
    ICON_SEGMENT = "\U0001f4c1"
    ICON_TASK = "\U0001f4dd"

    class TrackSelected(Message):
        def __init__(self, track: Track) -> None:
            self.track = track
            super().__init__()

    class TaskSelected(Message):
        def __init__(self, task: Task) -> None:
            self.task = task
            super().__init__()

    def load(self, blocks: list[WsBlock], expand_workspace_id: int | None = None) -> None:
        self.clear()
        self.root.set_label("Workspaces")
        self.root.data = None
        for ws in blocks:
            total = sum(len(tb.tasks) for tb in ws.tracks)
            ws_node = self.root.add(f"{self.ICON_WS} ({total}) {escape_markup(ws.workspace.name)}", data=ws.workspace)
            for tb in ws.tracks:
                self._add_track(ws_node, tb)
            if expand_workspace_id is not None and ws.workspace.id == expand_workspace_id:
                ws_node.expand()
        self.root.expand()

    def _add_track(self, ws_node, tb: TrackBlock) -> None:
        tnode = ws_node.add(f"{self.ICON_TRACK} ({len(tb.tasks)}) {escape_markup(tb.track.name)}", data=tb.track)
        by_parent: dict[int | None, list[Segment]] = {}
        root_seg: Segment | None = None
        for s in tb.segments:
            by_parent.setdefault(s.parent_segment_id, []).append(s)
            if s.is_root:
                root_seg = s
        tasks_by_seg: dict[int, list[Task]] = {}
        for t in tb.tasks:
            tasks_by_seg.setdefault(t.segment_id, []).append(t)
        if root_seg is not None:
            for t in tasks_by_seg.get(root_seg.id, []):
                tnode.add_leaf(self._task_label(t), data=t)
            for child in by_parent.get(root_seg.id, []):
                self._add_segment(tnode, child, by_parent, tasks_by_seg)

    def _add_segment(self, parent, seg: Segment, by_parent, tasks_by_seg) -> None:
        snode = parent.add(f"{self.ICON_SEGMENT} {escape_markup(seg.name)}", data=seg)
        for child in by_parent.get(seg.id, []):
            self._add_segment(snode, child, by_parent, tasks_by_seg)
        for t in tasks_by_seg.get(seg.id, []):
            snode.add_leaf(self._task_label(t), data=t)

    def _task_label(self, t: Task) -> str:
        prio = f" [dim](P{t.priority})[/dim]" if t.priority else ""
        return f"{self.ICON_TASK} {t.id:d}: {escape_markup(t.title)}{prio}"

    def show_empty(self, message: str) -> None:
        self.clear()
        self.root.set_label(message)

    # ── navigation (carried over from the old TUI) ──
    def key_left(self, event: events.Key) -> None:
        node = self.cursor_node
        if node is None:
            return
        if node.is_expanded:
            node.collapse()
        elif node.parent is not None:
            self.select_node(node.parent)
            self.scroll_to_node(node.parent)
        event.stop()

    def key_right(self, event: events.Key) -> None:
        node = self.cursor_node
        if node is None:
            return
        if node.allow_expand and not node.is_expanded:
            node.expand()
        elif node.is_expanded and node.children:
            self.select_node(node.children[0])
            self.scroll_to_node(node.children[0])
        event.stop()

    def on_tree_node_highlighted(self, event: Tree.NodeHighlighted) -> None:
        if isinstance(event.node.data, Track):
            self.post_message(self.TrackSelected(event.node.data))

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        event.stop()
        data = event.node.data
        if isinstance(data, Track):
            self.post_message(self.TrackSelected(data))
        elif isinstance(data, Task):
            self.post_message(self.TaskSelected(data))
