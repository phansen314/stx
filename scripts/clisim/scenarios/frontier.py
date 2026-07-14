"""Frontier (`next`) semantics through the CLI: blocker gating, terminal exclusion,
scoping, limit, ordering, and archived-ancestor exclusion."""
from __future__ import annotations

from harness import check, scene


def run(cli):
    scene("frontier: readiness, scoping & ordering")
    ws = cli.ws("front")
    tr = cli.track(ws, "t")
    a = cli.add(ws, "a", track=tr, priority=1)
    b = cli.add(ws, "b", track=tr, priority=5)
    cli.block(a, on=b)                       # b blocks a
    ids = cli.next_ids(ws)
    check(b in ids and a not in ids, "blocked task hidden; blocker is ready")

    # completing the blocker frees the dependent; terminal tasks drop out
    cli.mv(b, "in-progress")
    cli.done(b)
    ids2 = cli.next_ids(ws)
    check(a in ids2, "completing blocker unblocks dependent")
    check(b not in ids2, "terminal (done) task excluded from frontier")

    # scoping by track
    tr2 = cli.track(ws, "t2")
    c = cli.add(ws, "c", track=tr2)
    check(cli.next_ids(ws, track=tr2) == [c], "next -t scopes to a track")
    check(c not in cli.next_ids(ws, track=tr), "next -t on the other track excludes c")

    # --limit caps rows
    check(len(cli.next_ids(ws, limit=1)) == 1, "--limit caps the row count")

    # ordering: priority DESC, id ASC — a high-priority add sorts first
    d = cli.add(ws, "d", track=tr, priority=9)
    check(cli.next_ids(ws)[0] == d, "frontier ordered by priority DESC (highest first)")

    # segment-subtree scoping: next -s returns only the subtree's ready tasks
    tr3 = cli.track(ws, "t3")
    epic = cli.segment(ws, "epic", tr3)
    story = cli.segment(ws, "story", tr3, parent=epic)
    in_sub = cli.add(ws, "in-subtree", segment=story)
    on_root = cli.add(ws, "on-root", track=tr3)          # lands in tr3's root segment (outside epic)
    sub_ids = cli.next_ids(ws, segment=epic)
    check(in_sub in sub_ids, "next -s includes a task in the segment subtree")
    check(on_root not in sub_ids, "next -s excludes a task outside the subtree (track root)")

    # a task under an archived ancestor disappears
    cli.archive("track", tr2, yes=True)
    check(c not in cli.next_ids(ws), "task under archived ancestor excluded from frontier")
