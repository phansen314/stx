"""Edge semantics through the CLI: blocks DAG rejections, cross-workspace guards,
self-relate validation, and the relate-kinds drift reader."""
from __future__ import annotations

from harness import check, scene


def run(cli):
    scene("edges: blocks/relates rejections + relate-kinds")
    ws = cli.ws("edge")
    tr = cli.track(ws, "t")
    a = cli.add(ws, "a", track=tr)
    b = cli.add(ws, "b", track=tr)
    c = cli.add(ws, "c", track=tr)
    cli.block(b, on=a)                       # a -> b
    cli.block(c, on=b)                       # b -> c

    # DAG invariant: a cycle-closing edge and a self-edge are both rejected
    cli.expect_error("CycleRejected", "block", a, "--on", c)     # c -> a closes a->b->c->a
    cli.expect_error("CycleRejected", "block", a, "--on", a)     # self
    cli.expect_error("Duplicate", "block", b, "--on", a)         # a -> b already exists

    # cross-workspace edges rejected (block/relate take raw task ids → reach the daemon)
    ws2 = cli.ws("edge2")
    tr2 = cli.track(ws2, "t")
    f = cli.add(ws2, "foreign", track=tr2)
    cli.expect_error("CrossWorkspace", "block", f, "--on", a)
    cli.expect_error("CrossWorkspace", "relate", a, "--to", f, "--kind", "relates-to")

    # self-relation is a Validation reject
    cli.expect_error("Validation", "relate", a, "--to", a, "--kind", "relates-to")

    # relate-kinds: distinct, sorted, and surfaces drift (relates-to vs relates_to)
    cli.relate(a, b, "relates-to")
    cli.relate(b, c, "spawns")
    cli.relate(a, c, "relates_to")
    kinds = cli.relate_kinds(ws)
    check(kinds == sorted(kinds), "relate-kinds returned sorted")
    check({"relates-to", "relates_to", "spawns"} <= set(kinds),
          "relate-kinds surfaces drift (relates-to vs relates_to)")

    # unblock: removing the a→b edge frees b onto the frontier; a second removal is NotFound
    check(b not in cli.next_ids(ws), "b gated by blocker a before unblock")
    cli.unblock(b, on=a)
    check(b in cli.next_ids(ws), "unblock removes the edge; b becomes ready")
    cli.expect_error("NotFound", "unblock", b, "--on", a)   # already removed → not a silent no-op

    # unrelate: removing a live relation; removing a missing one errors
    cli.unrelate(a, b, "relates-to")
    cli.expect_error("NotFound", "unrelate", a, "--to", b, "--kind", "relates-to")
