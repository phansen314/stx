"""Archive semantics through the CLI: edge cascade / auto-unblock, container cascade,
gone (410) vs not-found (404), and the integrity-protecting rejections."""
from __future__ import annotations

from harness import check, scene


def run(cli):
    scene("archive: cascades, gone semantics & rejections")
    ws = cli.ws("arch")
    tr = cli.track(ws, "t")
    a = cli.add(ws, "a", track=tr)
    b = cli.add(ws, "b", track=tr)
    cli.block(b, on=a)                       # a blocks b
    check(b not in cli.next_ids(ws), "b gated by live blocker a")
    cli.archive("task", a)
    check(b in cli.next_ids(ws), "archiving blocker auto-unblocks dependent (edge cascade #4)")

    cli.expect_error("Gone", "archive", "task", a)              # already archived → 410
    cli.expect_error("NotFound", "archive", "task", 999999)     # missing → 404
    cli.expect_error("--yes", "archive", "track", tr)           # cascade needs confirmation

    # rejections protecting referential integrity
    tr2 = cli.track(ws, "t2")
    x = cli.add(ws, "x", track=tr2)
    root2 = cli.task(x)["task"]["segmentId"]
    cli.expect_error("Validation", "archive", "segment", root2)          # root-segment archive
    cli.expect_error("Validation", "status", "archive", "todo", "-w", ws)  # default status

    cli.status_new(ws, "wip", 5)
    cli.transition(ws, "todo", "wip")
    cli.mv(x, "wip")
    cli.expect_error("Validation", "status", "archive", "wip", "-w", ws)  # referenced by live task

    # kind archive NULL-cascades the referencing live task (#9)
    cli.kind_new(ws, "impl")
    y = cli.add(ws, "y", track=tr2, kind="impl")
    cli.run("kind", "archive", "impl", "-w", ws)
    check(cli.task(y)["task"]["kindId"] is None, "kind archive null-cascades to live task")

    # container cascade leaves no live descendant (#6)
    cli.archive("track", tr2, yes=True)
    ids = cli.next_ids(ws)
    check(x not in ids and y not in ids, "track archive cascade removes descendants from frontier")

    # gone semantics (D4): mutating a cascade-archived task → 410
    cli.expect_error("Gone", "edit", x, "--title", "zombie")
