#!/usr/bin/env python3
"""
stx developer-simulation integration test.

Drives the running stx daemon over HTTP exactly as a developer (or a local agent) would:
it curates a workspace, plans work with dependencies, drives tasks through their lifecycle,
queries the frontier, exercises every rejection path, and archives everything — pretty-printing
each action and asserting state after every step. A green run is end-to-end proof of the wire
contract (serialization, routing, status mapping, invariants) that the in-JVM tests can't cover.

Usage:
    pip install -r scripts/requirements.txt        # or: python3 -m venv .venv && ... && pip install requests

    python3 scripts/dev_sim.py                      # launch a FRESH daemon (temp DB), run, tear down
    python3 scripts/dev_sim.py --keep              # ... and keep the temp state dir (incl. journal.log)
    python3 scripts/dev_sim.py --no-build          # don't run `gradlew installDist` first
    python3 scripts/dev_sim.py --base-url URL      # ATTACH to an already-running daemon instead

Exit code 0 = all assertions passed; non-zero = first failure (printed with full context).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import requests

from harness import (
    Daemon, act, assert_count, bold, check, green, narrate, red, scene,
)

# ── HTTP client ───────────────────────────────────────────────────────────────────────────────

class Stx:
    def __init__(self, base_url: str):
        self.base = base_url.rstrip("/")
        self.s = requests.Session()

    def call(self, method: str, path: str, body=None, *, expect: int | None = None,
             error: str | None = None, quiet: bool = False):
        r = self.s.request(method, self.base + path, json=body, timeout=15)
        try:
            resp = r.json()
        except ValueError:
            resp = r.text
        if not quiet:
            act(method, path, body, r.status_code, resp)
        if expect is not None:
            check(r.status_code == expect, f"{method} {path} → {expect} (got {r.status_code}: {resp})")
        if error is not None:
            check(isinstance(resp, dict) and resp.get("error") == error,
                  f"{method} {path} → error '{error}' (got {resp})")
        return r.status_code, resp

    def get(self, p, **kw): return self.call("GET", p, **kw)
    def post(self, p, body=None, **kw): return self.call("POST", p, body, **kw)
    def patch(self, p, body=None, **kw): return self.call("PATCH", p, body, **kw)

    def raw_post(self, path: str, data: str):
        r = self.s.post(self.base + path, data=data,
                        headers={"Content-Type": "application/json"}, timeout=15)
        try:
            resp = r.json()
        except ValueError:
            resp = r.text
        act("POST", path, f"<raw> {data}", r.status_code, resp)
        return r.status_code, resp

    # convenience reads (quiet — used to fetch versions/ids without cluttering the log)
    def statuses(self, ws): return self.get(f"/workspaces/{ws}/statuses", quiet=True)[1]["items"]
    def status_id(self, ws, name): return next(s["id"] for s in self.statuses(ws) if s["name"] == name)
    def kinds(self, ws): return self.get(f"/workspaces/{ws}/kinds", quiet=True)[1]["items"]
    def task(self, tid): return self.get(f"/tasks/{tid}", quiet=True)[1]
    def version(self, tid): return self.task(tid)["task"]["version"]
    def frontier(self, ws, quiet=True, **scope):
        q = "&".join([f"workspace={ws}"] + [f"{k}={v}" for k, v in scope.items()])
        items = self.get(f"/next?{q}", quiet=quiet)[1]["items"]
        return [i["id"] for i in items]

    def move(self, ws, tid, to_name):
        """Move a task by status name using its current version (a small developer helper)."""
        return self.post(f"/tasks/{tid}/status",
                         {"toStatusId": self.status_id(ws, to_name), "expectedVersion": self.version(tid)})

# ── the simulation ──────────────────────────────────────────────────────────────────────────--

def simulate(stx: Stx, state_dir: str | None) -> None:
    # 1 ── bootstrap & discovery
    scene("1. Bootstrap a workspace")
    ws = stx.post("/workspaces", {"name": "acme", "metadataJson": '{"jira":"ACME"}'}, expect=200)[1]["id"]
    check(stx.get(f"/workspaces/{ws}/statuses", quiet=True)[1] is not None, "workspace queryable")
    sts = stx.statuses(ws)
    names = {s["name"] for s in sts}
    check({"todo", "in-progress", "done"} <= names, "seeded statuses present")
    check(sum(1 for s in sts if s["isDefault"]) == 1, "exactly one default status")
    check(next(s for s in sts if s["name"] == "todo")["isDefault"], "todo is the default")
    check(next(s for s in sts if s["name"] == "done")["terminal"], "done is terminal")
    listed = stx.get("/workspaces", expect=200)[1]["items"]
    check(any(w["id"] == ws for w in listed), "new workspace shows in listing")

    # 2 ── curate vocabulary
    scene("2. Curate vocabulary (kinds, statuses, transitions, default)")
    impl = stx.post(f"/workspaces/{ws}/kinds", {"name": "impl"}, expect=200)[1]["id"]
    review = stx.post(f"/workspaces/{ws}/kinds", {"name": "review"}, expect=200)[1]["id"]
    stx.post(f"/workspaces/{ws}/kinds", {"name": "research"}, expect=200)
    research_kind = next(k["id"] for k in stx.kinds(ws) if k["name"] == "research")
    blocked = stx.post(f"/workspaces/{ws}/statuses", {"name": "blocked", "kanbanOrder": 3}, expect=200)[1]["id"]
    stx.post(f"/workspaces/{ws}/transitions",
             {"fromStatusId": stx.status_id(ws, "todo"), "toStatusId": blocked}, expect=200)
    stx.post(f"/workspaces/{ws}/transitions",
             {"fromStatusId": blocked, "toStatusId": stx.status_id(ws, "in-progress")}, expect=200)
    check(len(stx.get(f"/workspaces/{ws}/transitions", quiet=True)[1]["items"]) == 6,
          "transitions listed (4 seeded + 2 added)")
    # move the create-time default to in-progress, verify, then restore to todo
    stx.post(f"/workspaces/{ws}/statuses/{stx.status_id(ws, 'in-progress')}/default", expect=200)
    check(next(s for s in stx.statuses(ws) if s["isDefault"])["name"] == "in-progress", "default moved")
    stx.post(f"/workspaces/{ws}/statuses/{stx.status_id(ws, 'todo')}/default", expect=200)
    check(next(s for s in stx.statuses(ws) if s["isDefault"])["name"] == "todo", "default restored to todo")

    # 3 ── structure the work
    scene("3. Structure tracks & segments")
    auth = stx.post(f"/workspaces/{ws}/tracks", {"name": "auth", "description": "authn/z"}, expect=200)[1]["id"]
    segs = stx.get(f"/tracks/{auth}/segments", expect=200)[1]["items"]
    check(len(segs) == 1 and segs[0]["isRoot"], "track auto-created exactly one root segment")
    epic = stx.post(f"/tracks/{auth}/segments", {"name": "login epic"}, expect=200)[1]["id"]
    story = stx.post(f"/tracks/{auth}/segments", {"name": "oauth story", "parentSegmentId": epic}, expect=200)[1]["id"]
    billing = stx.post(f"/workspaces/{ws}/tracks", {"name": "billing"}, expect=200)[1]["id"]

    # 4 ── create tasks
    scene("4. Create tasks")
    a1 = stx.post(f"/tracks/{auth}/tasks", {"title": "design auth", "kindId": impl, "priority": 5}, expect=200)[1]
    check(a1["workspaceId"] == ws, "task workspace_id derived from container")
    check(a1["statusId"] == stx.status_id(ws, "todo"), "no-status task lands on default (todo)")
    check(a1["kindId"] == impl, "kind set")
    a1 = a1["id"]
    a2 = stx.post(f"/segments/{story}/tasks", {"title": "impl login", "kindId": impl}, expect=200)[1]["id"]
    a3 = stx.post(f"/segments/{story}/tasks", {"title": "review login", "kindId": review}, expect=200)[1]["id"]
    a4 = stx.post(f"/segments/{epic}/tasks", {"title": "write docs", "kindId": research_kind, "priority": 1}, expect=200)[1]["id"]
    b1 = stx.post(f"/tracks/{billing}/tasks", {"title": "billing api", "kindId": impl}, expect=200)[1]["id"]

    # 5 ── dependencies & relations
    scene("5. Plan dependencies & relations")
    stx.post("/blocks", {"sourceTaskId": a1, "targetTaskId": a2}, expect=200)   # a1 -> a2
    stx.post("/blocks", {"sourceTaskId": a2, "targetTaskId": a3}, expect=200)   # a2 -> a3
    stx.post("/blocks", {"sourceTaskId": a1, "targetTaskId": b1}, expect=200)   # cross-track: a1 -> b1
    stx.post("/relates", {"kind": "relates-to", "sourceTaskId": a2, "targetTaskId": a3}, expect=200)
    stx.post("/relates", {"kind": "relates-to", "sourceTaskId": a3, "targetTaskId": a2}, expect=200)  # reciprocal
    stx.post("/relates", {"kind": "spawns", "sourceTaskId": a1, "targetTaskId": a2}, expect=200)
    stx.post("/relates", {"kind": "spawns", "sourceTaskId": a2, "targetTaskId": a1}, expect=200)       # reciprocal directional
    detail = stx.get(f"/tasks/{a2}", expect=200)[1]
    check(a1 in detail["blocksIn"] and a3 in detail["blocksOut"], "edges embedded on GET /tasks/{id}")
    rel_to_a3 = [r for r in detail["relates"] if r["otherTaskId"] == a3 and r["kind"] == "relates-to"]
    check(len(rel_to_a3) == 1, "symmetric relates-to shown once (deduped)")
    check(any(r["kind"] == "spawns" for r in detail["relates"]), "spawns relation present")

    # 6 ── frontier scopes
    scene("6. Query the frontier (all scopes)")
    check(set(stx.frontier(ws)) == {a1, a4}, "workspace frontier = {a1, a4} (others blocked)")
    check(stx.frontier(ws, track=auth) == [a1] or set(stx.frontier(ws, track=auth)) == {a1, a4},
          "auth-scoped frontier ready set")
    check(stx.frontier(ws, track=billing) == [], "billing gated by cross-track blocker a1")
    check(set(stx.frontier(ws, segment=epic)) == {a4}, "epic subtree frontier = {a4}")
    check(set(stx.frontier(ws, kind=impl)) == {a1}, "kind=impl frontier = {a1} (research/blocked excluded)")
    check(set(stx.frontier(ws, kind=research_kind)) == {a4}, "kind=research frontier = {a4}")

    # 7 ── lifecycle & kanban
    scene("7. Work the lifecycle & kanban")
    stx.move(ws, a1, "in-progress")
    check(a1 in stx.frontier(ws), "in-progress task stays in the frontier")
    inprog = stx.status_id(ws, "in-progress")
    kanban = stx.get(f"/tracks/{auth}/tasks?status={inprog}", expect=200)[1]["items"]
    check([t["id"] for t in kanban] == [a1], "kanban: auth in-progress column = [a1]")
    stx.move(ws, a1, "done")
    check({a2, a4, b1} <= set(stx.frontier(ws)), "completing a1 unblocks a2 and cross-track b1")
    stx.patch(f"/tasks/{a2}", {"expectedVersion": stx.version(a2), "priority": 9, "description": "use authlib"}, expect=200)
    check(stx.task(a2)["task"]["priority"] == 9, "edit applied (priority bumped)")
    # complete a2, then rework it to re-gate a3
    stx.move(ws, a2, "in-progress")
    stx.move(ws, a2, "done")
    check(a3 in stx.frontier(ws), "completing a2 unblocks a3")
    stx.move(ws, a2, "in-progress")  # rework (done -> in-progress)
    check(a3 not in stx.frontier(ws), "rework re-gates a3 (recompute-on-read)")

    # 8 ── self-defending rejections
    scene("8. Self-defending rejections")
    stx.post("/blocks", {"sourceTaskId": a3, "targetTaskId": a1}, expect=409, error="CycleRejected")   # closes a1->a2->a3->a1
    stx.post("/blocks", {"sourceTaskId": a1, "targetTaskId": a1}, expect=409, error="CycleRejected")   # self
    stx.post("/blocks", {"sourceTaskId": a1, "targetTaskId": a2}, expect=409, error="Duplicate")       # live dup
    ws2 = stx.post("/workspaces", {"name": "other"}, expect=200)[1]["id"]
    t_other = stx.post(f"/tracks/{stx.post(f'/workspaces/{ws2}/tracks', {'name':'x'}, quiet=True)[1]['id']}/tasks",
                       {"title": "foreign"}, expect=200)[1]["id"]
    stx.post("/blocks", {"sourceTaskId": a1, "targetTaskId": t_other}, expect=409, error="CrossWorkspace")
    stx.post(f"/tasks/{a4}/status", {"toStatusId": stx.status_id(ws, "done"), "expectedVersion": stx.version(a4)},
             expect=409, error="IllegalTransition")  # todo -> done not a transition
    stx.patch(f"/tasks/{a4}", {"expectedVersion": 999, "title": "stale"}, expect=409, error="VersionConflict")
    stx.get("/tasks/999999", expect=404, error="NotFound")
    check(stx.raw_post("/workspaces", '{"nam')[0] == 400, "malformed body → 400")
    stx.get("/next", expect=400)  # missing workspace
    stx.post(f"/workspaces/{ws}/statuses/{stx.status_id(ws, 'todo')}/archive", expect=400, error="Validation")  # default
    # referenced (non-default) status: free todo from default, then archive it (a4 still on todo) → referenced reject
    stx.post(f"/workspaces/{ws}/statuses/{stx.status_id(ws, 'in-progress')}/default", expect=200)
    stx.post(f"/workspaces/{ws}/statuses/{stx.status_id(ws, 'todo')}/archive", expect=400, error="Validation")
    stx.post(f"/workspaces/{ws}/statuses/{stx.status_id(ws, 'todo')}/default", expect=200)  # restore
    root_seg = next(s for s in stx.get(f"/tracks/{auth}/segments", quiet=True)[1]["items"] if s["isRoot"])
    stx.post(f"/segments/{root_seg['id']}/archive", expect=400, error="Validation")  # root-segment archive

    # 9 ── archive cascades & gone
    # State here: a1 done; a2 in-progress (reworked) blocking a3; a3 gated; a4 free; b1 free (a1 done).
    scene("9. Archive cascades & gone semantics")
    # blocker archive (#4 edge cascade): a2 (in-progress) gates a3; archiving a2 frees a3.
    check(a3 not in stx.frontier(ws), "a3 gated by in-progress blocker a2 before archive")
    stx.post(f"/tasks/{a2}/archive", expect=200)
    check(a3 in stx.frontier(ws), "archiving blocker a2 auto-unblocks a3")
    # kind null-cascade (#9) on a still-live referencing task (b1 has kind impl)
    stx.post(f"/workspaces/{ws}/kinds/{impl}/archive", expect=200)
    check(stx.task(b1)["task"]["kindId"] is None, "archiving kind null-cascades referencing live task")
    # status archive (#9): the unused, non-default 'blocked' status retires cleanly
    stx.post(f"/workspaces/{ws}/statuses/{blocked}/archive", expect=200)
    check("blocked" not in {s["name"] for s in stx.statuses(ws)}, "archived status gone from listing")
    # container cascade (#6): archiving the epic segment removes its whole subtree (a3, a4)
    stx.post(f"/segments/{epic}/archive", expect=200)
    check(not ({a3, a4} & set(stx.frontier(ws))), "segment subtree archive removes its tasks from next")
    # gone semantics (D4): a3 is now archived via the cascade
    stx.patch(f"/tasks/{a3}", {"expectedVersion": stx.version(a3), "title": "zombie"}, expect=410, error="Gone")
    got = stx.get(f"/tasks/{a3}", expect=200)[1]
    check(got["task"]["archived"] is True, "direct GET still returns the archived task (D4)")
    # archive the workspace -> cascades every track (incl. billing/b1); frontier empties
    stx.post(f"/tracks/{auth}/archive", expect=200)
    stx.post(f"/workspaces/{ws}/archive", expect=200)
    check(stx.frontier(ws) == [], "archiving the workspace empties its frontier")

    # 10 ── journal (fresh-launch only)
    if state_dir:
        scene("10. Journal (non-authoritative, commit-order)")
        jpath = Path(state_dir) / "stx" / "journal.log"
        check(jpath.exists(), f"journal.log exists at {jpath}")
        lines = [l for l in jpath.read_text().splitlines() if l.strip()]
        check(len(lines) > 0, f"journal has {len(lines)} lines")
        verbs = [json.loads(l)["verb"] for l in lines]
        check("CreateWorkspace" in verbs and "AddBlocks" in verbs, "journal records issued verbs in commit order")
        narrate(f"journal verbs (first 6): {verbs[:6]}")

# ── entrypoint ──────────────────────────────────────────────────────────────────────────────--

def main() -> int:
    ap = argparse.ArgumentParser(description="stx developer-simulation integration test")
    ap.add_argument("--base-url", help="attach to an already-running daemon instead of launching one")
    ap.add_argument("--no-build", action="store_true", help="do not run gradlew installDist")
    ap.add_argument("--keep", action="store_true", help="keep the temp state dir (fresh-launch mode)")
    args = ap.parse_args()

    try:
        with Daemon(base_url=args.base_url, build=not args.no_build, keep=args.keep) as d:
            stx = Stx(d.base_url)
            simulate(stx, d.state_dir)
    except AssertionError as e:
        print("\n" + red(bold(f"✗ ASSERTION FAILED: {e}")))
        return 1
    except Exception as e:  # noqa: BLE001
        print("\n" + red(bold(f"✗ ERROR: {type(e).__name__}: {e}")))
        return 2
    print("\n" + green(bold(f"✓ all {assert_count()} assertions passed")))
    return 0

if __name__ == "__main__":
    sys.exit(main())
