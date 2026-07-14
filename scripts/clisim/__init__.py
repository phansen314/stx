"""CLI-driven integration suite for the stx daemon.

Drives the real CLI (`python -m cli`, the same entrypoint as the `bin/stx` launcher)
against a fresh temp-DB daemon and asserts the daemon's model + semantics THROUGH the
CLI — including CLI-only logic (arg validation, name/id resolution, retry, error
rendering) that the HTTP suite (scripts/dev_sim.py) can't reach. TUI is out of scope.
"""
