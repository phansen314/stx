"""RegistryModal — manage a workspace's statuses / kinds / transitions (add-only + archive +
set-default; rename/reorder/transition-removal are daemon gaps, deferred).

Stateless one-op-per-invocation, like EdgeModal: every add/archive/set-default control dismisses a
single op dict; the app applies it, reloads, and re-opens the modal with refreshed registries so
edits chain. The modal never touches the client.

Op dicts:
    {"op": "add_status",     "name": str, "kanban_order": int, "terminal": bool}
    {"op": "set_default",    "status_id": int}
    {"op": "archive_status", "status_id": int}
    {"op": "add_kind",       "name": str}
    {"op": "archive_kind",   "kind_id": int}
    {"op": "add_transition", "from": int, "to": int}
"""
from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Input, Label, Select, Static

from ..markup import escape_markup
from stxc.models import Kind, Status, Transition
from .base_edit import ModalScroll


class RegistryModal(ModalScreen[dict | None]):
    BINDINGS = [Binding("escape", "cancel", "Close", priority=True)]

    def __init__(
        self,
        statuses: list[Status],
        kinds: list[Kind],
        transitions: list[Transition],
        status_names: dict[int, str],
    ) -> None:
        super().__init__()
        self._statuses = statuses
        self._kinds = kinds
        self._transitions = transitions
        self._status_names = status_names
        self._ops: dict[str, dict] = {}  # button id → op dict

    def _row(self, text: str, buttons: list[tuple[str, dict]]) -> Horizontal:
        children: list = [Static(text, classes="edge-label")]
        for label, op in buttons:
            bid = f"reg-btn-{len(self._ops)}"
            self._ops[bid] = op
            children.append(Button(label, id=bid, classes="edge-remove"))
        return Horizontal(*children, classes="edge-row")

    def compose(self) -> ComposeResult:
        with ModalScroll(classes="modal-container"):
            yield Static("Registry", classes="modal-id")

            yield Label("Statuses", classes="form-label")
            for s in self._statuses:
                star = "★ " if s.is_default else ""
                term = " [terminal]" if s.terminal else ""
                btns: list[tuple[str, dict]] = []
                if not s.is_default:
                    btns.append(("default", {"op": "set_default", "status_id": s.id}))
                btns.append(("archive", {"op": "archive_status", "status_id": s.id}))
                yield self._row(f"{star}{escape_markup(s.name)}{term}", btns)
            with Horizontal(classes="edge-row"):
                yield Input(placeholder="new status", id="reg-status-name", classes="form-field")
                yield Checkbox("terminal", id="reg-status-terminal")
                yield Button("add", id="reg-add-status", classes="edge-remove")

            yield Label("Kinds", classes="form-label")
            if not self._kinds:
                yield Static("— none —", classes="edge-empty")
            for k in self._kinds:
                yield self._row(escape_markup(k.name), [("archive", {"op": "archive_kind", "kind_id": k.id})])
            with Horizontal(classes="edge-row"):
                yield Input(placeholder="new kind", id="reg-kind-name", classes="form-field")
                yield Button("add", id="reg-add-kind", classes="edge-remove")

            yield Label("Transitions (add-only)", classes="form-label")
            if not self._transitions:
                yield Static("— none —", classes="edge-empty")
            for t in self._transitions:
                frm = self._status_names.get(t.from_status_id, f"#{t.from_status_id}")
                to = self._status_names.get(t.to_status_id, f"#{t.to_status_id}")
                yield Static(f"{escape_markup(frm)} → {escape_markup(to)}", classes="edge-label")
            opts = [(escape_markup(s.name), s.id) for s in self._statuses]
            with Horizontal(classes="edge-row"):
                yield Select(opts, prompt="from…", id="reg-trans-from", classes="form-field")
                yield Select(opts, prompt="to…", id="reg-trans-to", classes="form-field")
                yield Button("add", id="reg-add-transition", classes="edge-remove")

            yield Static("", id="modal-error", classes="modal-error")
            with Horizontal(classes="modal-buttons"):
                yield Button("Close", id="modal-cancel")

    # ── interaction ──
    def action_cancel(self) -> None:
        self.dismiss(None)

    def _error(self, msg: str) -> None:
        self.query_one("#modal-error", Static).update(msg)

    def _next_status_order(self) -> int:
        return max((s.kanban_order for s in self._statuses), default=-1) + 1

    def _add_status(self) -> None:
        name = self.query_one("#reg-status-name", Input).value.strip()
        if not name:
            self._error("status name required")
            return
        terminal = self.query_one("#reg-status-terminal", Checkbox).value
        self.dismiss({
            "op": "add_status", "name": name,
            "kanban_order": self._next_status_order(), "terminal": bool(terminal),
        })

    def _add_kind(self) -> None:
        name = self.query_one("#reg-kind-name", Input).value.strip()
        if not name:
            self._error("kind name required")
            return
        self.dismiss({"op": "add_kind", "name": name})

    def _add_transition(self) -> None:
        frm = self.query_one("#reg-trans-from", Select).value
        to = self.query_one("#reg-trans-to", Select).value
        if frm is Select.NULL or to is Select.NULL:
            self._error("pick from and to")
            return
        if frm == to:
            self._error("from and to must differ")
            return
        self.dismiss({"op": "add_transition", "from": int(frm), "to": int(to)})

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "modal-cancel":
            self.dismiss(None)
        elif bid == "reg-add-status":
            self._add_status()
        elif bid == "reg-add-kind":
            self._add_kind()
        elif bid == "reg-add-transition":
            self._add_transition()
        elif bid in self._ops:
            self.dismiss(self._ops[bid])
