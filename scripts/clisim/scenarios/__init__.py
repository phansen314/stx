"""Scenario registry: name → callable(cli). Order here is the default run order."""
from __future__ import annotations

from . import archive, coherence, edges, frontier, lifecycle

SCENARIOS = {
    "lifecycle": lifecycle.run,
    "frontier": frontier.run,
    "edges": edges.run,
    "archive": archive.run,
    "coherence": coherence.run,
}
