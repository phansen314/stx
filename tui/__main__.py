"""Entrypoint: python3 -m tui --base-url http://127.0.0.1:8420"""
from __future__ import annotations

import argparse
import sys

from .app import StxApp
from stxc import Client


def main() -> int:
    ap = argparse.ArgumentParser(prog="tui", description="stx daemon TUI")
    ap.add_argument("--base-url", default="http://127.0.0.1:8420", help="daemon base URL")
    args = ap.parse_args()

    if not Client(args.base_url).ping():
        print(f"daemon not reachable at {args.base_url} — start it with ./gradlew run", file=sys.stderr)
        return 1

    StxApp(args.base_url).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
