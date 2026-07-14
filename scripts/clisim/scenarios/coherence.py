"""CLI-side resolution guards — the logic the HTTP suite can't reach.

The CLI resolves --workspace/--track/--status/--kind to concrete entities WITHIN the
target workspace before calling the daemon, so bad refs and cross-workspace refs are
rejected client-side as CliError (never reaching the daemon's CrossWorkspace rail).
This scenario pins that behavior."""
from __future__ import annotations

from harness import check, scene


def run(cli):
    scene("coherence: CLI name/id resolution guards")
    ws = cli.ws("coh")
    tr = cli.track(ws, "t")
    t = cli.add(ws, "task", track=tr)

    # unknown refs are rejected with a clear message naming the entity kind
    cli.expect_error("workspace", "next", "-w", "nope-ws")
    cli.expect_error("track", "add", "z", "-w", ws, "-t", "ghost")
    cli.expect_error("status", "mv", t, "ghoststatus")
    cli.expect_error("kind", "add", "z", "-w", ws, "-t", tr, "--kind", "ghostkind")

    # a status that exists ONLY in another workspace is NOT resolvable here —
    # proving the CLI scopes resolution per workspace (pre-empts daemon CrossWorkspace).
    ws2 = cli.ws("coh2")
    cli.status_new(ws2, "special", 7)
    cli.expect_error("status", "add", "z", "-w", ws, "-t", tr, "--status", "special")

    # name and id resolve to the same entity
    by_name = set(cli.next_ids(ws, track="t"))
    by_id = set(cli.next_ids(ws, track=tr))
    check(by_name == by_id, "track resolves identically by name and by id")
