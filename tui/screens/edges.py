"""EdgeModal — view/add/remove a task's blocks and relates edges.

Stateless by design: it renders the task's current edges (from a GetTask detail dict) and returns
a SINGLE operation dict on dismiss — the app applies it, reloads, and re-opens this modal with
fresh detail so the list always reflects daemon truth and edits chain naturally. Escape (returns
None) ends the loop. The modal never touches the client itself.

Op dicts returned via ``dismiss``:
    {"op": "add_blocks",    "source": int, "target": int}
    {"op": "add_relates",   "kind": str, "source": int, "target": int}
    {"op": "remove_blocks", "source": int, "target": int}
    {"op": "remove_relates","kind": str, "source": int, "target": int}
"""
from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Select, Static

from ..markup import escape_markup
from stxc.models import Task
from .base_edit import ModalScroll

# add-edge type options (label, value)
_ADD_TYPES = [
    ("this blocks →", "blocks_out"),
    ("← blocks this", "blocks_in"),
    ("relates →", "relates"),
]


class EdgeModal(ModalScreen[dict | None]):
    BINDINGS = [
        Binding("escape", "cancel", "Close", priority=True),
    ]

    def __init__(self, task: Task, detail: dict, ws_tasks: list[Task]) -> None:
        super().__init__()
        self._task_data = task
        self._blocks_in: list[int] = list(detail.get("blocksIn") or [])
        self._blocks_out: list[int] = list(detail.get("blocksOut") or [])
        self._relates: list[dict] = list(detail.get("relates") or [])
        self._labels = {t.id: t.title for t in ws_tasks}
        self._ws_tasks = ws_tasks
        # button-id → op dict, populated as remove rows are composed
        self._remove_ops: dict[str, dict] = {}

    # ── rendering ──
    def _label(self, tid: int) -> str:
        title = self._labels.get(tid)
        return f"#{tid}: {escape_markup(title)}" if title else f"#{tid}"

    def _remove_row(self, text: str, op: dict) -> Horizontal:
        bid = f"edge-rm-{len(self._remove_ops)}"
        self._remove_ops[bid] = op
        return Horizontal(
            Static(text, classes="edge-label"),
            Button("remove", id=bid, classes="edge-remove"),
            classes="edge-row",
        )

    def compose(self) -> ComposeResult:
        me = self._task_data.id
        with ModalScroll(classes="modal-container"):
            yield Static(f"Edges — {self._label(me)}", classes="modal-id")

            yield Label("Blocked by", classes="form-label")
            if not self._blocks_in:
                yield Static("— none —", classes="edge-empty")
            for src in self._blocks_in:
                yield self._remove_row(
                    self._label(src), {"op": "remove_blocks", "source": src, "target": me}
                )

            yield Label("Blocks", classes="form-label")
            if not self._blocks_out:
                yield Static("— none —", classes="edge-empty")
            for tgt in self._blocks_out:
                yield self._remove_row(
                    self._label(tgt), {"op": "remove_blocks", "source": me, "target": tgt}
                )

            yield Label("Relates", classes="form-label")
            if not self._relates:
                yield Static("— none —", classes="edge-empty")
            for r in self._relates:
                other, kind, outgoing = r["otherTaskId"], r["kind"], r.get("outgoing", True)
                arrow = "→" if outgoing else "←"
                src, tgt = (me, other) if outgoing else (other, me)
                yield self._remove_row(
                    f"[{escape_markup(kind)}] {arrow} {self._label(other)}",
                    {"op": "remove_relates", "kind": kind, "source": src, "target": tgt},
                )

            yield Static("Add edge", classes="form-label")
            yield Select(_ADD_TYPES, value="blocks_out", allow_blank=False, id="e-type", classes="form-field")
            yield Select(
                [(f"{t.id}: {t.title}", t.id) for t in self._ws_tasks],
                prompt="pick task…", id="e-target", classes="form-field",
            )
            yield Input(value="relates-to", id="e-kind", classes="form-field")
            yield Static("", id="modal-error", classes="modal-error")
            with Horizontal(classes="modal-buttons"):
                yield Button("Add", id="edge-add", variant="primary")
                yield Button("Close", id="modal-cancel")

    # ── interaction ──
    def action_cancel(self) -> None:
        self.dismiss(None)

    def _error(self, msg: str) -> None:
        self.query_one("#modal-error", Static).update(msg)

    def _do_add(self) -> None:
        me = self._task_data.id
        etype = self.query_one("#e-type", Select).value
        target = self.query_one("#e-target", Select).value
        if target is Select.NULL:
            self._error("pick a target task")
            return
        target = int(target)
        if etype == "blocks_out":
            self.dismiss({"op": "add_blocks", "source": me, "target": target})
        elif etype == "blocks_in":
            self.dismiss({"op": "add_blocks", "source": target, "target": me})
        else:
            kind = self.query_one("#e-kind", Input).value.strip() or "relates-to"
            self.dismiss({"op": "add_relates", "kind": kind, "source": me, "target": target})

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "edge-add":
            self._do_add()
        elif bid == "modal-cancel":
            self.dismiss(None)
        elif bid in self._remove_ops:
            self.dismiss(self._remove_ops[bid])
