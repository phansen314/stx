"""cli/context.py — name/id reference resolution. Pure (duck-typed .id/.name objects)."""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from cli.context import CliError, _as_id, _pick, kind, status


@dataclass
class Item:
    id: int
    name: str


class TestAsId:
    def test_none(self) -> None:
        assert _as_id(None) is None

    def test_numeric_string(self) -> None:
        assert _as_id("5") == 5

    def test_negative_numeric_string(self) -> None:
        # lstrip("-") then isdigit -> recognised as numeric, int() keeps the sign.
        assert _as_id("-3") == -3

    def test_int_input(self) -> None:
        assert _as_id(7) == 7

    def test_non_numeric(self) -> None:
        assert _as_id("auth") is None
        assert _as_id("1a") is None
        assert _as_id("") is None


class TestPick:
    def _items(self) -> list[Item]:
        return [Item(1, "todo"), Item(2, "doing")]

    def test_match_by_id(self) -> None:
        assert _pick(self._items(), "2", "status").name == "doing"

    def test_match_by_name(self) -> None:
        assert _pick(self._items(), "todo", "status").id == 1

    def test_unknown_id(self) -> None:
        with pytest.raises(CliError, match="no status with id 9"):
            _pick(self._items(), "9", "status")

    def test_unknown_name_lists_available_sorted(self) -> None:
        with pytest.raises(CliError, match="available: doing, todo"):
            _pick(self._items(), "nope", "status")

    def test_empty_list_available_none(self) -> None:
        with pytest.raises(CliError, match=r"available: \(none\)"):
            _pick([], "x", "status")

    def test_ambiguous_name(self) -> None:
        items = [Item(1, "dup"), Item(2, "dup")]
        with pytest.raises(CliError, match="ambiguous"):
            _pick(items, "dup", "status")


class TestStatusKindWrappers:
    def test_status_delegates_to_pick(self) -> None:
        assert status([Item(3, "done")], "done").id == 3

    def test_kind_delegates_to_pick(self) -> None:
        with pytest.raises(CliError, match="no kind named"):
            kind([Item(1, "impl")], "research")
