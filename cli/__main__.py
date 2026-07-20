"""stx — stateless CLI over the stx daemon. `python3 -m cli ...` (or the `bin/stx` launcher).

Every workspace-scoped command takes -w/--workspace explicitly (name or id); nothing is stored,
so concurrent Claude sessions / sub-agents never interfere. --json on any command emits raw data.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from stxc import Client, StxApiError, StxError

from . import context, render
from .context import CliError

DEFAULT_URL = os.environ.get("STX_URL", "http://127.0.0.1:8420")


# ── helpers ──────────────────────────────────────────────────────────────────
def _client(args) -> Client:
    c = Client(args.base_url)
    if not c.ping():
        raise CliError(f"daemon unreachable at {args.base_url} — start it with ./gradlew run")
    return c


def _status_names(c: Client, ws_id: int) -> dict[int, str]:
    return {s.id: s.name for s in c.statuses(ws_id)}


def _kind_names(c: Client, ws_id: int) -> dict[int, str]:
    return {k.id: k.name for k in c.kinds(ws_id)}


def _emit(args, text: str, payload) -> None:
    print(render.dumps(payload) if args.json else text)


# ── orientation ──────────────────────────────────────────────────────────────
def cmd_ls(c, args):
    rows = [(ws, len(c.tracks(ws.id))) for ws in c.list_workspaces()]
    _emit(args, render.workspaces(rows),
          [{"id": ws.id, "name": ws.name, "tracks": n} for ws, n in rows])


def cmd_relate_kinds(c, args):
    ws = context.workspace(c, args.workspace)
    kinds = c.relates_kinds(ws.id)
    _emit(args, render.relates_kinds(kinds), {"items": kinds})


def cmd_tree(c, args):
    ws = context.workspace(c, args.workspace)
    blocks = [(t, c.segments(t.id), c.track_tasks(t.id)) for t in c.tracks(ws.id)]
    sn = _status_names(c, ws.id)
    payload = {"workspace": ws.name, "tracks": [
        {"track": t.name, "id": t.id,
         "tasks": [{"id": x.id, "title": x.title, "priority": x.priority,
                    "status": sn.get(x.status_id), "segmentId": x.segment_id} for x in tasks]}
        for t, _segs, tasks in blocks]}
    _emit(args, render.tree(ws, blocks, sn), payload)


def cmd_next(c, args):
    ws = context.workspace(c, args.workspace)
    tr_id = context.track(c, ws.id, args.track).id if args.track else None
    items = c.next(ws.id, track=tr_id, segment=args.segment, limit=args.limit)
    sn = _status_names(c, ws.id)
    _emit(args, render.frontier(items, sn), items)


def cmd_show(c, args):
    detail = c.task_detail(args.id)
    ws_id = detail["task"]["workspaceId"]
    _emit(args, render.task_detail(detail, _status_names(c, ws_id), _kind_names(c, ws_id)), detail)


# ── task mutations ───────────────────────────────────────────────────────────
def cmd_add(c, args):
    ws = context.workspace(c, args.workspace)
    if bool(args.track) == bool(args.segment):
        raise CliError("pass exactly one of -t/--track or -s/--segment")
    status_id = context.status(c.statuses(ws.id), args.status).id if args.status else None
    kind_id = context.kind(c.kinds(ws.id), args.kind).id if args.kind else None
    track_id = context.track(c, ws.id, args.track).id if args.track else None
    task = c.create_task(track=track_id, segment=args.segment, title=args.title,
                         description=args.desc or "", priority=args.priority,
                         status_id=status_id, kind_id=kind_id)
    _emit(args, f"added #{task.id}  {task.title}", task)


def _retry_conflict(c, task_id, fn):
    """Run fn(version); on VersionConflict re-read once and retry."""
    version = c.task_detail(task_id)["task"]["version"]
    try:
        return fn(version)
    except StxApiError as e:
        if e.variant != "VersionConflict":
            raise
        version = c.task_detail(task_id)["task"]["version"]
        return fn(version)


def cmd_mv(c, args):
    detail = c.task_detail(args.id)
    ws_id = detail["task"]["workspaceId"]
    statuses = c.statuses(ws_id)
    target = context.status(statuses, args.status)
    try:
        task = _retry_conflict(c, args.id, lambda v: c.move_status(args.id, target.id, v))
    except StxApiError as e:
        if e.variant == "IllegalTransition":
            cur = detail["task"]["statusId"]
            sn = {s.id: s.name for s in statuses}
            legal = [sn[t.to_status_id] for t in c.transitions(ws_id) if t.from_status_id == cur]
            raise CliError(f"illegal transition to {target.name!r}. legal from "
                           f"{sn.get(cur, cur)!r}: {', '.join(legal) or '(none)'}")
        raise CliError(str(e))
    _emit(args, f"ok #{task.id} → {target.name}", task)


def cmd_edit(c, args):
    changes: dict = {}
    if args.title is not None:
        changes["title"] = args.title
    if args.desc is not None:
        changes["description"] = args.desc
    if args.priority is not None:
        changes["priority"] = args.priority
    if args.kind is not None:
        ws_id = c.task_detail(args.id)["task"]["workspaceId"]
        changes["kindId"] = context.kind(c.kinds(ws_id), args.kind).id
    if args.clear_kind:
        changes["clearKind"] = True
    if not changes:
        raise CliError("nothing to edit — pass --title/--desc/--priority/--kind/--clear-kind")
    task = _retry_conflict(c, args.id, lambda v: c.edit_task(args.id, v, **changes))
    _emit(args, f"edited #{task.id}  {task.title}", task)


def cmd_done(c, args):
    detail = c.task_detail(args.id)
    ws_id = detail["task"]["workspaceId"]
    statuses = c.statuses(ws_id)
    terminal = next((s for s in statuses if s.terminal), None)
    if terminal is None:
        raise CliError("no terminal status defined in this workspace")
    try:
        task = _retry_conflict(c, args.id, lambda v: c.move_status(args.id, terminal.id, v))
    except StxApiError as e:
        if e.variant == "IllegalTransition":
            cur = detail["task"]["statusId"]
            sn = {s.id: s.name for s in statuses}
            legal = [sn[t.to_status_id] for t in c.transitions(ws_id) if t.from_status_id == cur]
            raise CliError(f"can't reach terminal {terminal.name!r} directly. legal from "
                           f"{sn.get(cur, cur)!r}: {', '.join(legal) or '(none)'}")
        raise CliError(str(e))
    _emit(args, f"done #{task.id} → {terminal.name}", task)


# ── metadata (key/value over each entity's free-form JSON blob) ───────────────
def _parse_value(s: str):
    """Parse a `set` value as JSON, falling back to the raw string on parse failure."""
    try:
        return json.loads(s)
    except ValueError:
        return s


def _meta_load(blob: str | None) -> dict:
    d = json.loads(blob or "{}")
    if not isinstance(d, dict):
        raise CliError("metadata is not a JSON object")
    return d


def _meta_target(c, args):
    """Resolve the meta selector → (read, write). Exactly one of --task / -w; --track needs -w.

    read() → (blob_str, version) freshly; write(version, blob_str) → updated entity. The daemon
    has no per-key ops, so set/del are client-side read-modify-write over the CAS `edit_*` methods.
    """
    has_task = args.task is not None
    has_ws = args.workspace is not None
    if has_task == has_ws:
        raise CliError("pass exactly one target: --task <id> or -w <workspace>")
    if args.track and not has_ws:
        raise CliError("--track requires -w <workspace>")

    if has_task:
        def read():
            t = c.task_detail(args.task)["task"]
            return t["metadataJson"], t["version"]
        return read, lambda v, blob: c.edit_task(args.task, v, metadata_json=blob)

    ws_id = context.workspace(c, args.workspace).id
    if args.track:
        tr_id = context.track(c, ws_id, args.track).id
        def read():
            tr = context.track(c, ws_id, args.track)
            return tr.metadata_json, tr.version
        return read, lambda v, blob: c.edit_track(tr_id, v, metadata_json=blob)

    def read():
        w = context.workspace(c, args.workspace)
        return w.metadata_json, w.version
    return read, lambda v, blob: c.edit_workspace(ws_id, v, metadata_json=blob)


def _meta_rmw(read, write, mutate):
    """Read blob → mutate(dict) in place → write, with one CAS retry on VersionConflict."""
    def attempt():
        blob, ver = read()
        d = _meta_load(blob)
        mutate(d)
        return write(ver, json.dumps(d))
    try:
        return attempt()
    except StxApiError as e:
        if e.variant != "VersionConflict":
            raise
        return attempt()


def cmd_meta(c, args):
    read, write = _meta_target(c, args)
    if args.sub == "ls":
        d = _meta_load(read()[0])
        _emit(args, render.meta(d), d)
    elif args.sub == "get":
        d = _meta_load(read()[0])
        if args.key not in d:
            raise CliError(f"no metadata key {args.key!r}")
        _emit(args, render.meta({args.key: d[args.key]}), {args.key: d[args.key]})
    elif args.sub == "set":
        value = args.value if args.string else _parse_value(args.value)
        _meta_rmw(read, write, lambda d: d.__setitem__(args.key, value))
        _emit(args, f"{args.key} = {json.dumps(value)}", {args.key: value})
    elif args.sub == "del":
        if args.key not in _meta_load(read()[0]):
            raise CliError(f"no metadata key {args.key!r}")
        _meta_rmw(read, write, lambda d: d.pop(args.key, None))
        _emit(args, f"deleted {args.key}", {"deleted": args.key})


# ── edges ────────────────────────────────────────────────────────────────────
def cmd_block(c, args):
    res = c.add_blocks(source_task_id=args.on, target_task_id=args.id)
    _emit(args, f"#{args.id} now blocked by #{args.on}", res)


def cmd_relate(c, args):
    res = c.add_relates(kind=args.kind, source_task_id=args.id, target_task_id=args.to)
    _emit(args, f"#{args.id} {args.kind} #{args.to}", res)


def cmd_unblock(c, args):
    res = c.remove_blocks(source_task_id=args.on, target_task_id=args.id)
    _emit(args, f"#{args.id} no longer blocked by #{args.on}", res)


def cmd_unrelate(c, args):
    res = c.remove_relates(kind=args.kind, source_task_id=args.id, target_task_id=args.to)
    _emit(args, f"#{args.id} no longer {args.kind} #{args.to}", res)


# ── archive ──────────────────────────────────────────────────────────────────
_ARCHIVE_PATH = {"task": "tasks", "segment": "segments", "track": "tracks", "workspace": "workspaces"}


def cmd_archive(c, args):
    if args.type in ("track", "workspace") and not args.yes:
        raise CliError(f"archiving a {args.type} cascades to its children — pass --yes to confirm")
    c.archive(_ARCHIVE_PATH[args.type], args.id)
    _emit(args, f"archived {args.type} #{args.id}", {"archived": args.type, "id": args.id})


# ── containers ───────────────────────────────────────────────────────────────
def cmd_ws(c, args):
    if args.sub == "new":
        ws = c.create_workspace(args.name)
        _emit(args, f"workspace #{ws.id}  {ws.name}", ws)


def cmd_track(c, args):
    if args.sub == "new":
        ws = context.workspace(c, args.workspace)
        tr = c.create_track(ws.id, args.name, description=args.desc or "")
        _emit(args, f"track #{tr.id}  {tr.name}", tr)


def cmd_segment(c, args):
    if args.sub == "new":
        ws = context.workspace(c, args.workspace)
        tr = context.track(c, ws.id, args.track)
        seg = c.create_segment(tr.id, args.name, parent_segment_id=args.parent)
        _emit(args, f"segment #{seg.id}  {seg.name}", seg)


def cmd_status(c, args):
    ws = context.workspace(c, args.workspace)
    if args.sub == "new":
        s = c.create_status(ws.id, args.name, args.order, terminal=args.terminal)
        _emit(args, f"status #{s.id}  {s.name}", s)
    elif args.sub == "default":
        s = context.status(c.statuses(ws.id), args.status)
        c.set_default_status(ws.id, s.id)
        _emit(args, f"default status → {s.name}", {"default": s.name})
    elif args.sub == "archive":
        s = context.status(c.statuses(ws.id), args.status)
        c.archive_status(ws.id, s.id)
        _emit(args, f"archived status {s.name}", {"archived": "status", "id": s.id})


def cmd_kind(c, args):
    ws = context.workspace(c, args.workspace)
    if args.sub == "new":
        k = c.create_kind(ws.id, args.name)
        _emit(args, f"kind #{k.id}  {k.name}", k)
    elif args.sub == "archive":
        k = context.kind(c.kinds(ws.id), args.name)
        c.archive_kind(ws.id, k.id)
        _emit(args, f"archived kind {k.name}", {"archived": "kind", "id": k.id})


def cmd_transition(c, args):
    ws = context.workspace(c, args.workspace)
    statuses = c.statuses(ws.id)
    f = context.status(statuses, getattr(args, "from"))
    t = context.status(statuses, args.to)
    tr = c.create_transition(ws.id, f.id, t.id)
    _emit(args, f"transition {f.name} → {t.name}", tr)


# ── parser ───────────────────────────────────────────────────────────────────
def _global_parser() -> argparse.ArgumentParser:
    """The `--base-url`/`--json` globals, parsed separately so they work in ANY position.

    argparse copies a `parents=`-shared option onto each subparser with its own default, and the
    subparser namespace then clobbers a value given *before* the subcommand. So instead of sharing
    the flags, `parse_cli` strips them from the whole argv up front with this parser (see there).
    They stay on `common` below too, purely so `--help` documents them at both levels.
    """
    gp = argparse.ArgumentParser(add_help=False)
    gp.add_argument("--base-url", default=DEFAULT_URL, help=f"daemon URL (default {DEFAULT_URL})")
    gp.add_argument("--json", action="store_true", help="emit raw JSON instead of compact text")
    return gp


def parse_cli(argv=None) -> argparse.Namespace:
    """Parse argv accepting the global flags before OR after the subcommand.

    Phase 1: pull `--base-url`/`--json` out of argv wherever they sit. Phase 2: parse the remaining
    tokens (subcommand + its args) normally, then stamp the resolved globals back on.
    """
    if argv is None:
        argv = sys.argv[1:]
    globals_ns, rest = _global_parser().parse_known_args(argv)
    args = build_parser().parse_args(rest)
    args.base_url = globals_ns.base_url
    args.json = globals_ns.json
    return args


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--base-url", default=DEFAULT_URL, help=f"daemon URL (default {DEFAULT_URL})")
    common.add_argument("--json", action="store_true", help="emit raw JSON instead of compact text")

    p = argparse.ArgumentParser(prog="stx", parents=[common], description="stateless CLI over the stx daemon")
    sub = p.add_subparsers(dest="cmd", required=True)

    def add(name, fn, help):
        sp = sub.add_parser(name, parents=[common], help=help)
        sp.set_defaults(fn=fn)
        return sp

    def w(sp):  # add the required -w workspace flag
        sp.add_argument("-w", "--workspace", help="workspace name or id (required)")
        return sp

    add("ls", cmd_ls, "list workspaces")
    w(add("tree", cmd_tree, "show a workspace as a tree"))
    sp = w(add("next", cmd_next, "ready tasks (frontier)"))
    sp.add_argument("-t", "--track", help="scope to a track (name or id)")
    sp.add_argument("-s", "--segment", type=int, help="scope to a segment subtree (id)")
    sp.add_argument("--limit", type=int, help="max rows")

    sp = add("show", cmd_show, "task detail + edges")
    sp.add_argument("id", type=int)

    sp = w(add("add", cmd_add, "create a task"))
    sp.add_argument("title")
    sp.add_argument("-t", "--track", help="track name or id")
    sp.add_argument("-s", "--segment", type=int, help="segment id")
    sp.add_argument("-p", "--priority", type=int, default=0)
    sp.add_argument("--status", help="initial status name or id")
    sp.add_argument("--kind", help="kind name or id")
    sp.add_argument("--desc", help="description")

    sp = add("mv", cmd_mv, "move a task's status")
    sp.add_argument("id", type=int)
    sp.add_argument("status", help="target status name or id")

    sp = add("edit", cmd_edit, "edit a task")
    sp.add_argument("id", type=int)
    sp.add_argument("--title")
    sp.add_argument("--desc")
    sp.add_argument("--priority", type=int)
    sp.add_argument("--kind")
    sp.add_argument("--clear-kind", action="store_true")

    sp = add("done", cmd_done, "move a task to the terminal status")
    sp.add_argument("id", type=int)

    sp = add("block", cmd_block, "mark a task blocked by another")
    sp.add_argument("id", type=int, help="the blocked task")
    sp.add_argument("--on", type=int, required=True, help="the blocker task")

    sp = add("relate", cmd_relate, "add a relation between tasks")
    sp.add_argument("id", type=int)
    sp.add_argument("--to", type=int, required=True)
    sp.add_argument("--kind", required=True, help="relation kind (e.g. relates_to, spawns)")

    sp = add("unblock", cmd_unblock, "remove a blocks edge (mirror of `block`)")
    sp.add_argument("id", type=int, help="the blocked task")
    sp.add_argument("--on", type=int, required=True, help="the blocker task")

    sp = add("unrelate", cmd_unrelate, "remove a relation (mirror of `relate`)")
    sp.add_argument("id", type=int)
    sp.add_argument("--to", type=int, required=True)
    sp.add_argument("--kind", required=True, help="relation kind to remove")

    w(add("relate-kinds", cmd_relate_kinds, "list relation kinds currently in use"))

    # metadata: `meta {ls|get|set|del}` on a task (--task), workspace (-w), or track (-w --track)
    meta = sub.add_parser("meta", parents=[common], help="get/set/delete an entity's metadata keys")
    msub = meta.add_subparsers(dest="sub", required=True)

    def sel(sp):  # the task/workspace/track target selector, shared by every meta verb
        sp.add_argument("--task", type=int, help="target task id")
        sp.add_argument("-w", "--workspace", help="target workspace (name or id)")
        sp.add_argument("--track", help="target track under -w (name or id)")
        return sp

    sel(msub.add_parser("ls", parents=[common], help="list all metadata keys"))
    g = sel(msub.add_parser("get", parents=[common], help="print one key")); g.add_argument("key")
    s = sel(msub.add_parser("set", parents=[common], help="set a key (value parsed as JSON)"))
    s.add_argument("key"); s.add_argument("value")
    s.add_argument("--string", action="store_true", help="store value as a literal string, not JSON")
    d = sel(msub.add_parser("del", parents=[common], help="delete a key")); d.add_argument("key")
    meta.set_defaults(fn=cmd_meta)

    sp = add("archive", cmd_archive, "archive an entity")
    sp.add_argument("type", choices=list(_ARCHIVE_PATH))
    sp.add_argument("id", type=int)
    sp.add_argument("--yes", action="store_true", help="confirm cascading archive (track/workspace)")

    # containers / registries (two-level: `stx ws new …`)
    sp = sub.add_parser("ws", parents=[common], help="workspace admin")
    ssub = sp.add_subparsers(dest="sub", required=True)
    n = ssub.add_parser("new", parents=[common]); n.add_argument("name"); sp.set_defaults(fn=cmd_ws)
    sp.set_defaults(fn=cmd_ws)

    sp = sub.add_parser("track", parents=[common], help="track admin")
    ssub = sp.add_subparsers(dest="sub", required=True)
    n = w(ssub.add_parser("new", parents=[common])); n.add_argument("name"); n.add_argument("--desc")
    sp.set_defaults(fn=cmd_track)

    sp = sub.add_parser("segment", parents=[common], help="segment admin")
    ssub = sp.add_subparsers(dest="sub", required=True)
    n = w(ssub.add_parser("new", parents=[common]))
    n.add_argument("name"); n.add_argument("-t", "--track", required=True); n.add_argument("--parent", type=int)
    sp.set_defaults(fn=cmd_segment)

    sp = sub.add_parser("status", parents=[common], help="status admin")
    ssub = sp.add_subparsers(dest="sub", required=True)
    n = w(ssub.add_parser("new", parents=[common]))
    n.add_argument("name"); n.add_argument("--order", type=int, required=True); n.add_argument("--terminal", action="store_true")
    d = w(ssub.add_parser("default", parents=[common])); d.add_argument("status")
    a = w(ssub.add_parser("archive", parents=[common])); a.add_argument("status")
    sp.set_defaults(fn=cmd_status)

    sp = sub.add_parser("kind", parents=[common], help="kind admin")
    ssub = sp.add_subparsers(dest="sub", required=True)
    n = w(ssub.add_parser("new", parents=[common])); n.add_argument("name")
    a = w(ssub.add_parser("archive", parents=[common])); a.add_argument("name")
    sp.set_defaults(fn=cmd_kind)

    sp = w(sub.add_parser("transition", parents=[common], help="add a status transition"))
    sp.add_argument("--from", required=True, help="from status name or id")
    sp.add_argument("--to", required=True, help="to status name or id")
    sp.set_defaults(fn=cmd_transition, sub="new")

    return p


def main(argv=None) -> int:
    args = parse_cli(argv)
    try:
        client = _client(args)
        args.fn(client, args)
        return 0
    except CliError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except StxApiError as e:
        print(f"error: {e.variant or e.code}: {e}", file=sys.stderr)
        return 1
    except StxError as e:
        # Daemon crash / timeout / connection drop mid-command: the client wraps every transport
        # failure in StxConnError (a StxError subclass, NOT requests.RequestException), so catch the
        # base here for a clean message instead of a traceback.
        print(f"error: daemon request failed: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
