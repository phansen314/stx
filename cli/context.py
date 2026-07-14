"""Reference resolution: turn a user-supplied name-or-id into a concrete entity.

Stateless — every resolver takes the ref explicitly; nothing is read from disk or env (except the
daemon base URL, which is shared infra, not per-session identity). A failed resolution raises
CliError, which the entrypoint prints as `error: …` and exits non-zero.
"""
from __future__ import annotations

from stxc import Client, Kind, Status, Track, Workspace


class CliError(Exception):
    """A user-facing error: printed as `error: <message>`, exit code 1."""


def _as_id(ref: str | int | None) -> int | None:
    if ref is None:
        return None
    s = str(ref)
    return int(s) if s.lstrip("-").isdigit() else None


def _pick(items: list, ref: str | int, kind: str):
    """Match ref against items by id (if numeric) else by exact name; error on miss/ambiguity."""
    rid = _as_id(ref)
    if rid is not None:
        for it in items:
            if it.id == rid:
                return it
        raise CliError(f"no {kind} with id {rid}")
    matches = [it for it in items if it.name == str(ref)]
    if not matches:
        names = ", ".join(sorted(it.name for it in items)) or "(none)"
        raise CliError(f"no {kind} named {ref!r}. available: {names}")
    if len(matches) > 1:
        raise CliError(f"{kind} name {ref!r} is ambiguous ({len(matches)} matches) — use an id")
    return matches[0]


def workspace(client: Client, ref: str | int | None) -> Workspace:
    if ref is None:
        raise CliError("--workspace required (e.g. -w auth-rewrite)")
    return _pick(client.list_workspaces(), ref, "workspace")


def track(client: Client, ws_id: int, ref: str | int) -> Track:
    return _pick(client.tracks(ws_id), ref, "track")


def status(statuses: list[Status], ref: str | int) -> Status:
    return _pick(statuses, ref, "status")


def kind(kinds: list[Kind], ref: str | int) -> Kind:
    return _pick(kinds, ref, "kind")
