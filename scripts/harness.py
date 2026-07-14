#!/usr/bin/env python3
"""Shared integration-test harness for the stx daemon.

Transport-agnostic building blocks used by both integration suites:
  - scripts/dev_sim.py       drives the daemon over raw HTTP (wire contract)
  - scripts/clisim/          drives the real CLI (`python -m cli`) end-to-end

Only process/port/assert/pretty helpers live here. The request layer (HTTP session vs
CLI subprocess) belongs to each suite. Extracted from dev_sim.py so the launcher is
defined once.
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from pprint import pformat

import requests

ROOT = Path(__file__).resolve().parent.parent
STX_BIN = ROOT / "build" / "install" / "stx" / "bin" / "stx"

# ── pretty output ─────────────────────────────────────────────────────────────────────────────

_TTY = sys.stdout.isatty()
def _c(code: str, s: str) -> str:
    return f"\033[{code}m{s}\033[0m" if _TTY else s
def bold(s): return _c("1", s)
def dim(s): return _c("2", s)
def green(s): return _c("32", s)
def red(s): return _c("31", s)
def cyan(s): return _c("36", s)
def yellow(s): return _c("33", s)

_ASSERTS = 0

def assert_count() -> int:
    return _ASSERTS

def scene(title: str) -> None:
    print("\n" + bold(cyan(f"━━━ {title} " + "━" * max(0, 60 - len(title)))))

def narrate(msg: str) -> None:
    print(dim(f"    · {msg}"))

def _short(obj, limit: int = 600) -> str:
    text = pformat(obj, width=100, compact=True)
    return text if len(text) <= limit else text[:limit] + dim(" …")

def act(method: str, path: str, req, status: int, resp) -> None:
    color = green if 200 <= status < 300 else (yellow if 400 <= status < 500 else red)
    print(f"  {bold(method):<6} {path}")
    if req is not None:
        import json
        print(dim(f"      req  {json.dumps(req)}"))
    print(f"      {color('← ' + str(status))}  {_short(resp)}")

def check(cond: bool, msg: str) -> None:
    global _ASSERTS
    if not cond:
        raise AssertionError(msg)
    _ASSERTS += 1
    print(green(f"      ✓ {msg}"))

# ── daemon lifecycle ──────────────────────────────────────────────────────────────────────────

def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]

class Daemon:
    """Launch a fresh daemon against a temp XDG_STATE_HOME, or (with base_url) attach to a running one."""
    def __init__(self, *, base_url: str | None, build: bool, keep: bool):
        self.attach = base_url
        self.build = build
        self.keep = keep
        self.proc: subprocess.Popen | None = None
        self.state_dir: str | None = None
        self.base_url: str = base_url or ""

    def __enter__(self) -> "Daemon":
        if self.attach:
            narrate(f"attaching to {self.attach}")
            _wait_health(self.attach)
            return self
        if self.build and not STX_BIN.exists():
            narrate("building distribution (gradlew installDist)…")
            subprocess.run(["./gradlew", "installDist", "-q"], cwd=ROOT, check=True)
        if not STX_BIN.exists():
            sys.exit(f"daemon binary not found at {STX_BIN} (run without --no-build)")
        port = free_port()
        self.state_dir = tempfile.mkdtemp(prefix="stx-sim-")
        self.base_url = f"http://127.0.0.1:{port}"
        env = {**os.environ, "STX_PORT": str(port), "XDG_STATE_HOME": self.state_dir}
        narrate(f"launching daemon on {self.base_url} (state: {self.state_dir})")
        self.proc = subprocess.Popen([str(STX_BIN)], env=env,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
        _wait_health(self.base_url)
        return self

    def __exit__(self, *exc):
        if self.proc:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        if self.state_dir and not self.keep:
            import shutil
            shutil.rmtree(self.state_dir, ignore_errors=True)
        elif self.state_dir:
            narrate(f"kept state dir: {self.state_dir}")

def _wait_health(base: str, timeout: float = 40.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if requests.get(base + "/health", timeout=2).status_code == 200:
                return
        except requests.RequestException:
            pass
        time.sleep(0.3)
    sys.exit(f"daemon at {base} did not become healthy within {timeout}s")
