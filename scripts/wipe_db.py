#!/usr/bin/env python3
"""Delete a sticky-notes database and its associated files.

Usage:
    python scripts/wipe_db.py [DB_PATH] [--yes]

Deletes: <DB_PATH>, <DB_PATH>-wal, <DB_PATH>-shm, and <DB_DIR>/active-board.
This is intentionally NOT a `todo` subcommand — destructive operations are
kept off the agent-accessible CLI surface.

Defaults:
    DB_PATH  ~/.local/share/sticky-notes/sticky-notes.db
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sticky_notes.active_board import active_board_path
from sticky_notes.connection import DEFAULT_DB_PATH


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Delete the sticky-notes database and active-board pointer."
    )
    parser.add_argument(
        "db",
        nargs="?",
        default=str(DEFAULT_DB_PATH),
        help=f"path to SQLite database (default: {DEFAULT_DB_PATH})",
    )
    parser.add_argument("-y", "--yes", action="store_true", help="skip confirmation prompt")
    args = parser.parse_args()

    db = Path(args.db)
    targets = [
        db,
        db.with_name(db.name + "-wal"),
        db.with_name(db.name + "-shm"),
        active_board_path(db),
    ]

    existing = [p for p in targets if p.exists()]
    if not existing:
        print("Nothing to delete — no sticky-notes files found at:")
        for p in targets:
            print(f"  {p}")
        return

    print("The following files will be deleted:")
    for p in existing:
        print(f"  {p}")

    if not args.yes:
        resp = input("Proceed? [y/N] ").strip().lower()
        if resp not in ("y", "yes"):
            print("Aborted.", file=sys.stderr)
            sys.exit(1)

    for p in targets:
        if p.exists():
            p.unlink()
            print(f"deleted: {p}")
        else:
            print(f"(already gone): {p}")

    print()
    print("To recreate a board, run one of:")
    print("  todo board create <name>")
    print("  todo board use <existing-name>")


if __name__ == "__main__":
    main()
