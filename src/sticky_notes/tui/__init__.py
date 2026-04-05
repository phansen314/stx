from __future__ import annotations

import sys
from pathlib import Path

from sticky_notes.tui.app import StickyNotesApp


def main(argv: list[str] | None = None) -> None:
    db_path: Path | None = None
    args = argv if argv is not None else sys.argv[1:]
    for i, arg in enumerate(args):
        if arg == "--db" and i + 1 < len(args):
            db_path = Path(args[i + 1])
            break
    StickyNotesApp(db_path=db_path).run()
