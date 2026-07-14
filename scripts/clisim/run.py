#!/usr/bin/env python3
"""stx CLI integration-test runner.

Launches a fresh temp-DB daemon (or attaches to a running one) and drives the real CLI
(`python -m cli`) through a set of scenarios that assert the daemon's model + semantics.

Usage:
    python scripts/clisim/run.py                 # build (if needed), launch, run all, tear down
    python scripts/clisim/run.py --only frontier # run one scenario area (comma-separated)
    python scripts/clisim/run.py --no-build      # don't run gradlew installDist first
    python scripts/clisim/run.py --keep          # keep the temp state dir
    python scripts/clisim/run.py --base-url URL  # attach to an already-running daemon

Exit 0 = all assertions passed; 1 = an assertion failed; 2 = unexpected error.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# scripts/ on the path so `import harness` and `import clisim` resolve when run as a file.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness import Daemon, assert_count, bold, green, narrate, red, scene  # noqa: E402
from clisim.cli import Cli  # noqa: E402
from clisim.scenarios import SCENARIOS  # noqa: E402

# Behaviors the CLI cannot reach — the HTTP suite (scripts/dev_sim.py) owns these.
# Printed after a run so "CLI green" never reads as "everything covered".
BOUNDARIES = [
    "malformed-JSON body / missing required param → 400  (raw HTTP only; dev_sim.raw_post)",
    "VersionConflict — the CLI's _retry_conflict re-reads a fresh version, so it can't be forced",
    "no CLI command for edit_workspace/edit_track, changes",
]


def main() -> int:
    ap = argparse.ArgumentParser(description="stx CLI integration-test runner")
    ap.add_argument("--base-url", help="attach to an already-running daemon instead of launching one")
    ap.add_argument("--no-build", action="store_true", help="do not run gradlew installDist")
    ap.add_argument("--keep", action="store_true", help="keep the temp state dir")
    ap.add_argument("--only", help="comma-separated scenario names to run (default: all)")
    args = ap.parse_args()

    names = args.only.split(",") if args.only else list(SCENARIOS)
    unknown = [n for n in names if n not in SCENARIOS]
    if unknown:
        sys.exit(f"unknown scenario(s): {', '.join(unknown)} — available: {', '.join(SCENARIOS)}")

    try:
        with Daemon(base_url=args.base_url, build=not args.no_build, keep=args.keep) as d:
            cli = Cli(d.base_url)
            for name in names:
                SCENARIOS[name](cli)
    except AssertionError as e:
        print("\n" + red(bold(f"✗ ASSERTION FAILED: {e}")))
        return 1
    except Exception as e:  # noqa: BLE001
        print("\n" + red(bold(f"✗ ERROR: {type(e).__name__}: {e}")))
        return 2

    scene("coverage boundaries (NOT exercised here — HTTP suite's job)")
    for b in BOUNDARIES:
        narrate(b)
    print("\n" + green(bold(f"✓ all {assert_count()} assertions passed "
                            f"({len(names)} scenario{'s' if len(names) != 1 else ''})")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
