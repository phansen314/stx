from __future__ import annotations

import sys
from pathlib import Path

from sticky_notes.tui.app import StickyNotesApp


def main() -> None:
    db_path: Path | None = None
    args = sys.argv[1:]
    for i, arg in enumerate(args):
        if arg == "--db" and i + 1 < len(args):
            db_path = Path(args[i + 1])
            break
    StickyNotesApp(db_path=db_path).run()
