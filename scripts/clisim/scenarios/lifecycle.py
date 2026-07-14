"""Task lifecycle through the CLI: add / mv / done / edit, plus CLI-side arg guards."""
from __future__ import annotations

from harness import check, scene


def run(cli):
    scene("lifecycle: add / mv / done / edit")
    ws = cli.ws("life")
    tr = cli.track(ws, "main")

    # `add` requires exactly one of -t/-s
    cli.expect_error("exactly one", "add", "orphan", "-w", ws)                       # neither
    t = cli.add(ws, "design", track=tr, priority=5)
    check(cli.status_name(ws, t) == "todo", "new task lands on default status (todo)")
    seg = cli.segment(ws, "epic", tr)
    cli.expect_error("exactly one", "add", "both", "-w", ws, "-t", tr, "-s", seg)    # both

    # legal move todo -> in-progress
    cli.mv(t, "in-progress")
    check(cli.status_name(ws, t) == "in-progress", "mv todo→in-progress applied")

    # illegal move: todo -> done is not a seeded transition; error names the legal set
    t2 = cli.add(ws, "second", track=tr)
    cli.expect_error("illegal transition", "mv", t2, "done")
    cli.expect_error("in-progress", "mv", t2, "done")     # legal-moves hint present

    # `done` reaches terminal via the legal path
    cli.mv(t2, "in-progress")
    cli.done(t2)
    check(cli.status_name(ws, t2) == "done", "done moves task to terminal status")

    # `edit` no-op guard + field edits, incl. --clear-kind
    cli.expect_error("nothing to edit", "edit", t)
    cli.kind_new(ws, "impl")
    tk = cli.add(ws, "kinded", track=tr, kind="impl")
    check(cli.task(tk)["task"]["kindId"] is not None, "task created with kind set")
    cli.edit(tk, clear_kind=True)
    check(cli.task(tk)["task"]["kindId"] is None, "--clear-kind nulls the kind")
    cli.edit(tk, priority=9)
    check(cli.task(tk)["task"]["priority"] == 9, "edit --priority applied")
