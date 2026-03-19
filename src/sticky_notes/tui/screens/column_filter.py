from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, OptionList, Static
from textual.widgets.option_list import Option

from sticky_notes.models import Column


class ColumnFilterModal(ModalScreen[frozenset[int] | None]):
    """Multi-select modal for filtering which columns are visible.

    Dismisses with:
    - frozenset[int]: selected column IDs (confirm)
    - None: cancel (no change)
    """

    DEFAULT_CSS = """
    ColumnFilterModal {
        align: center middle;
    }

    ColumnFilterModal #filter-container {
        width: 50;
        max-height: 60%;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }

    ColumnFilterModal #filter-title {
        text-style: bold;
        text-align: center;
        margin-bottom: 1;
    }

    ColumnFilterModal #filter-buttons {
        width: 100%;
        align: center middle;
        height: 3;
        margin-top: 1;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False),
        Binding("enter", "confirm", "Confirm", priority=True),
        Binding("space", "toggle", "Toggle", show=False),
    ]

    def __init__(
        self,
        columns: tuple[Column, ...],
        selected_ids: frozenset[int] | None,
    ) -> None:
        super().__init__()
        self._columns = columns
        self._selected: set[int] = (
            set(selected_ids) if selected_ids is not None else {c.id for c in columns}
        )

    def compose(self) -> ComposeResult:
        with Vertical(id="filter-container"):
            yield Static("Filter Columns", id="filter-title")
            yield OptionList(*self._build_options(), id="column-filter-list")
            with Horizontal(id="filter-buttons"):
                yield Button("OK", variant="primary", id="filter-ok")

    def _build_options(self) -> list[Option]:
        options: list[Option] = []
        for col in self._columns:
            marker = "\\[x]" if col.id in self._selected else "\\[ ]"
            options.append(Option(f"{marker} {col.name}", id=str(col.id)))
        return options

    def on_mount(self) -> None:
        self.query_one("#column-filter-list", OptionList).focus()

    def _toggle_highlighted(self) -> None:
        option_list = self.query_one("#column-filter-list", OptionList)
        idx = option_list.highlighted
        if idx is None:
            return
        option = option_list.get_option_at_index(idx)
        col_id = int(option.id)
        if col_id in self._selected:
            self._selected.discard(col_id)
        else:
            self._selected.add(col_id)
        # Rebuild options preserving highlight position
        option_list.clear_options()
        option_list.add_options(self._build_options())
        option_list.highlighted = idx

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        # Click or enter on a row toggles it
        event.stop()
        self._toggle_highlighted()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.action_confirm()

    def action_toggle(self) -> None:
        self._toggle_highlighted()

    def action_confirm(self) -> None:
        self.dismiss(frozenset(self._selected))

    def action_cancel(self) -> None:
        self.dismiss(None)
