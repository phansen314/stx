"""Cli — a subprocess wrapper around the real stx CLI (`python -m cli`).

Mirrors dev_sim.py's HTTP `class Stx`, but every call shells out to the CLI exactly as a
user/agent would, with STX_URL pointed at the test daemon. Reads use `--json` and return
parsed data; `expect_error` asserts the CLI's non-zero exit + surfaced error text.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

# clisim is scripts/clisim/; put scripts/ on the path so `import harness` resolves.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from harness import ROOT, act, check  # noqa: E402


class Cli:
    def __init__(self, base_url: str):
        self.base_url = base_url
        self.env = {**os.environ, "STX_URL": base_url, "PYTHONPATH": str(ROOT)}

    # ── raw invocation ─────────────────────────────────────────────────────────
    def _run(self, args, want_json: bool) -> subprocess.CompletedProcess:
        # NOTE: --json must come AFTER the subcommand — argparse's shared parent parser
        # resets the flag to False if it's placed before the subcommand.
        argv = [str(a) for a in args] + (["--json"] if want_json else [])
        return subprocess.run([sys.executable, "-m", "cli", *argv],
                              cwd=str(ROOT), env=self.env, capture_output=True, text=True)

    def run(self, *args, json_out: bool = True):
        """Run a command expected to succeed; return parsed JSON (or stdout text)."""
        p = self._run(args, json_out)
        status = 200 if p.returncode == 0 else 500
        act("stx", " ".join(str(a) for a in args), None, status,
            (p.stdout or p.stderr).strip()[:200])
        check(p.returncode == 0,
              f"stx {' '.join(str(a) for a in args)} → exit 0 (got {p.returncode}: {p.stderr.strip()})")
        if not json_out:
            return p.stdout.strip()
        return json.loads(p.stdout) if p.stdout.strip() else None

    def expect_error(self, contains: str, *args, code: int = 1):
        """Run a command expected to fail; assert exit code + that `contains` appears in output."""
        p = self._run(args, want_json=False)
        act("stx", " ".join(str(a) for a in args), None,
            400 if p.returncode else 200, (p.stderr or p.stdout).strip()[:200])
        check(p.returncode == code,
              f"stx {' '.join(str(a) for a in args)} → exit {code} "
              f"(got {p.returncode}: out={p.stdout.strip()!r} err={p.stderr.strip()!r})")
        blob = (p.stdout + p.stderr).lower()
        check(contains.lower() in blob,
              f"error mentions {contains!r} (got {(p.stdout + p.stderr).strip()!r})")
        return p

    # ── convenience builders (return ids) ───────────────────────────────────────
    def ws(self, name: str) -> int:
        return self.run("ws", "new", name)["id"]

    def track(self, ws: int, name: str, desc: str | None = None) -> int:
        args = ["track", "new", name, "-w", ws]
        if desc:
            args += ["--desc", desc]
        return self.run(*args)["id"]

    def segment(self, ws: int, name: str, track: int, parent: int | None = None) -> int:
        args = ["segment", "new", name, "-w", ws, "-t", track]
        if parent is not None:
            args += ["--parent", parent]
        return self.run(*args)["id"]

    def status_new(self, ws: int, name: str, order: int, terminal: bool = False) -> int:
        args = ["status", "new", name, "-w", ws, "--order", order]
        if terminal:
            args += ["--terminal"]
        return self.run(*args)["id"]

    def transition(self, ws: int, frm: str, to: str):
        return self.run("transition", "-w", ws, "--from", frm, "--to", to)

    def kind_new(self, ws: int, name: str) -> int:
        return self.run("kind", "new", name, "-w", ws)["id"]

    def add(self, ws: int, title: str, *, track=None, segment=None,
            priority=None, kind=None, status=None, desc=None) -> int:
        args = ["add", title, "-w", ws]
        if track is not None:
            args += ["-t", track]
        if segment is not None:
            args += ["-s", segment]
        if priority is not None:
            args += ["-p", priority]
        if kind is not None:
            args += ["--kind", kind]
        if status is not None:
            args += ["--status", status]
        if desc is not None:
            args += ["--desc", desc]
        return self.run(*args)["id"]

    def mv(self, task_id: int, status: str):
        return self.run("mv", task_id, status)

    def done(self, task_id: int):
        return self.run("done", task_id)

    def edit(self, task_id: int, **fields):
        args = ["edit", task_id]
        for k, v in fields.items():
            flag = "--" + k.replace("_", "-")
            args += [flag] if v is True else [flag, v]
        return self.run(*args)

    def block(self, task_id: int, on: int):
        return self.run("block", task_id, "--on", on)

    def relate(self, task_id: int, to: int, kind: str):
        return self.run("relate", task_id, "--to", to, "--kind", kind)

    def unblock(self, task_id: int, on: int):
        return self.run("unblock", task_id, "--on", on)

    def unrelate(self, task_id: int, to: int, kind: str):
        return self.run("unrelate", task_id, "--to", to, "--kind", kind)

    def archive(self, kind: str, entity_id: int, yes: bool = False):
        args = ["archive", kind, entity_id]
        if yes:
            args += ["--yes"]
        return self.run(*args)

    # ── reads ───────────────────────────────────────────────────────────────────
    def task(self, task_id: int) -> dict:
        return self.run("show", task_id)

    def tree(self, ws: int) -> dict:
        return self.run("tree", "-w", ws)

    def next_ids(self, ws: int, track=None, segment=None, limit=None) -> list[int]:
        args = ["next", "-w", ws]
        if track is not None:
            args += ["-t", track]
        if segment is not None:
            args += ["-s", segment]
        if limit is not None:
            args += ["--limit", limit]
        items = self.run(*args)
        return [i["id"] for i in items]

    def relate_kinds(self, ws: int) -> list[str]:
        return self.run("relate-kinds", "-w", ws)["items"]

    def status_name(self, ws: int, task_id: int) -> str | None:
        """Resolve a task's current status NAME via `tree` (which maps status id→name)."""
        for tr in self.tree(ws)["tracks"]:
            for t in tr["tasks"]:
                if t["id"] == task_id:
                    return t["status"]
        return None
