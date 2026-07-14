"""StxApp._segment_target — pure resolution of (track_id, parent_segment_id) for a new segment
from the focused tree-node data. Daemon-free / UI-free, like test_tui_explain."""
from __future__ import annotations

import pytest

pytest.importorskip("textual")

from stxc.models import Segment, Task, Track  # noqa: E402
from tui.app import StxApp  # noqa: E402


# track id → its root segment id
ROOTS = {5: 50, 7: 70, 4: 40}


class TestSegmentTarget:
    def test_on_segment_makes_a_child(self) -> None:
        seg = Segment(id=9, track_id=3)
        assert StxApp._segment_target(seg, None, ROOTS) == (3, 9)

    def test_on_track_parents_to_root_segment(self) -> None:
        assert StxApp._segment_target(Track(id=5), None, ROOTS) == (5, 50)

    def test_fallback_to_active_track_root(self) -> None:
        # cursor on a task (or anything non-container) → active track's root segment
        assert StxApp._segment_target(Task(id=1), Track(id=7), ROOTS) == (7, 70)
        assert StxApp._segment_target(None, Track(id=7), ROOTS) == (7, 70)

    def test_no_context_yields_none(self) -> None:
        assert StxApp._segment_target(None, None, ROOTS) == (None, None)

    def test_segment_wins_over_active_track(self) -> None:
        # an explicit segment cursor is honored even when an active track exists
        seg = Segment(id=2, track_id=4)
        assert StxApp._segment_target(seg, Track(id=99), ROOTS) == (4, 2)

    def test_track_without_cached_root_falls_back_to_none(self) -> None:
        # unknown track (no root cached yet) → parent None rather than crashing
        assert StxApp._segment_target(Track(id=123), None, ROOTS) == (123, None)
