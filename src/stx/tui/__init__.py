from __future__ import annotations

import sys
from pathlib import Path

from stx.tui.app import StxApp


def main(argv: list[str] | None = None) -> None:  # pragma: no cover
    db_path: Path | None = None
    config_path: Path | None = None
    args = argv if argv is not None else sys.argv[1:]
    for i, arg in enumerate(args):
        if arg == "--db" and i + 1 < len(args):
            db_path = Path(args[i + 1])
        elif arg == "--config" and i + 1 < len(args):
            config_path = Path(args[i + 1])
    StxApp(db_path=db_path, config_path=config_path).run()
