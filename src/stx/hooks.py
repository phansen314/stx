"""Event-driven hooks engine for stx.

Hook commands are executed via ``shell=True``. Anyone who can write
``~/.config/stx/hooks.toml`` can execute arbitrary code as the stx user;
this is by design, matching the trust model of git hooks and Claude Code hooks.

Hooks are post-only observers: they fire after the write transaction commits and
see committed state. The write always proceeds; hooks cannot veto operations.

Re-entrancy warning: a hook command that itself invokes ``stx`` will recursively
fire more hooks. There is no depth limit or cycle detection; avoid self-referential
hooks.
"""
from __future__ import annotations

import importlib.resources
import json
import subprocess
import tomllib
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class HookEvent(StrEnum):
    TASK_CREATED = "task.created"
    TASK_UPDATED = "task.updated"
    TASK_MOVED = "task.moved"
    TASK_DONE = "task.done"
    TASK_UNDONE = "task.undone"
    TASK_ARCHIVED = "task.archived"
    TASK_TRANSFERRED = "task.transferred"
    TASK_ASSIGNED = "task.assigned"
    TASK_UNASSIGNED = "task.unassigned"
    TASK_META_SET = "task.meta_set"
    TASK_META_REMOVED = "task.meta_removed"
    GROUP_CREATED = "group.created"
    GROUP_UPDATED = "group.updated"
    GROUP_ARCHIVED = "group.archived"
    GROUP_META_SET = "group.meta_set"
    GROUP_META_REMOVED = "group.meta_removed"
    WORKSPACE_CREATED = "workspace.created"
    WORKSPACE_UPDATED = "workspace.updated"
    WORKSPACE_ARCHIVED = "workspace.archived"
    WORKSPACE_META_SET = "workspace.meta_set"
    WORKSPACE_META_REMOVED = "workspace.meta_removed"
    STATUS_CREATED = "status.created"
    STATUS_UPDATED = "status.updated"
    STATUS_ARCHIVED = "status.archived"
    EDGE_CREATED = "edge.created"
    EDGE_ARCHIVED = "edge.archived"
    EDGE_UPDATED = "edge.updated"
    EDGE_META_SET = "edge.meta_set"
    EDGE_META_REMOVED = "edge.meta_removed"


class HookTiming(StrEnum):
    POST = "post"


EVENT_CATEGORIES: dict[HookEvent, str] = {
    HookEvent.TASK_CREATED: "created",
    HookEvent.GROUP_CREATED: "created",
    HookEvent.WORKSPACE_CREATED: "created",
    HookEvent.STATUS_CREATED: "created",
    HookEvent.EDGE_CREATED: "created",
    HookEvent.TASK_UPDATED: "updated",
    HookEvent.TASK_MOVED: "updated",
    HookEvent.TASK_DONE: "updated",
    HookEvent.TASK_UNDONE: "updated",
    HookEvent.TASK_ASSIGNED: "updated",
    HookEvent.TASK_UNASSIGNED: "updated",
    HookEvent.GROUP_UPDATED: "updated",
    HookEvent.WORKSPACE_UPDATED: "updated",
    HookEvent.STATUS_UPDATED: "updated",
    HookEvent.EDGE_UPDATED: "updated",
    HookEvent.TASK_ARCHIVED: "archived",
    HookEvent.GROUP_ARCHIVED: "archived",
    HookEvent.WORKSPACE_ARCHIVED: "archived",
    HookEvent.STATUS_ARCHIVED: "archived",
    HookEvent.EDGE_ARCHIVED: "archived",
    HookEvent.TASK_META_SET: "meta",
    HookEvent.TASK_META_REMOVED: "meta",
    HookEvent.GROUP_META_SET: "meta",
    HookEvent.GROUP_META_REMOVED: "meta",
    HookEvent.WORKSPACE_META_SET: "meta",
    HookEvent.WORKSPACE_META_REMOVED: "meta",
    HookEvent.EDGE_META_SET: "meta",
    HookEvent.EDGE_META_REMOVED: "meta",
    HookEvent.TASK_TRANSFERRED: "transferred",
}

DEFAULT_HOOKS_PATH = Path.home() / ".config" / "stx" / "hooks.toml"
DESCRIPTION_MAX_BYTES = 4096


@dataclass(frozen=True)
class HookConfig:
    event: HookEvent
    timing: HookTiming
    command: str
    workspace: str | None = None
    name: str | None = None
    enabled: bool = True


def _parse_hook_entry(raw: dict, index: int) -> HookConfig:
    for field in ("event", "timing", "command"):
        if field not in raw:
            raise ValueError(f"hooks[{index}]: missing required field '{field}'")

    raw_event = raw["event"]
    try:
        event = HookEvent(raw_event)
    except ValueError as exc:
        valid = ", ".join(e.value for e in HookEvent)
        raise ValueError(
            f"hooks[{index}]: invalid event '{raw_event}'. Valid values: {valid}"
        ) from exc

    raw_timing = raw["timing"]
    if raw_timing == "pre":
        raise ValueError(
            f"hooks[{index}]: timing='pre' is no longer supported — stx hooks are "
            f"post-only observers. Change timing to 'post' or omit it (defaults to 'post')."
        )
    try:
        timing = HookTiming(raw_timing)
    except ValueError as exc:
        raise ValueError(
            f"hooks[{index}]: invalid timing '{raw_timing}'. Must be 'post'"
        ) from exc

    command = raw["command"]
    if not isinstance(command, str) or not command.strip():
        raise ValueError(f"hooks[{index}]: 'command' must be a non-empty string")

    workspace = raw.get("workspace")
    if workspace is not None and not isinstance(workspace, str):
        raise ValueError(f"hooks[{index}]: 'workspace' must be a string")

    name = raw.get("name")
    if name is not None and not isinstance(name, str):
        raise ValueError(f"hooks[{index}]: 'name' must be a string")

    enabled = raw.get("enabled", True)
    if not isinstance(enabled, bool):
        raise ValueError(f"hooks[{index}]: 'enabled' must be a boolean")

    return HookConfig(
        event=event,
        timing=timing,
        command=command,
        workspace=workspace,
        name=name,
        enabled=enabled,
    )


def load_hooks(path: Path = DEFAULT_HOOKS_PATH) -> tuple[HookConfig, ...]:
    """Parse hooks.toml and return all hook configs. Returns () if file is missing."""
    if not path.exists():
        return ()

    with open(path, "rb") as f:
        try:
            data = tomllib.load(f)
        except tomllib.TOMLDecodeError as exc:
            raise ValueError(f"hooks config parse error: {exc}") from exc

    raw_hooks = data.get("hooks", [])
    if not raw_hooks:
        return ()

    errors: list[str] = []
    configs: list[HookConfig] = []
    for i, raw in enumerate(raw_hooks):
        try:
            configs.append(_parse_hook_entry(raw, i))
        except ValueError as exc:
            errors.append(str(exc))

    if errors:
        raise ValueError("\n".join(errors))

    return tuple(configs)


def validate_hooks_config(path: Path = DEFAULT_HOOKS_PATH) -> list[str]:
    """Return a list of error strings. Empty list means the config is valid."""
    if not path.exists():
        return []

    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    except tomllib.TOMLDecodeError as exc:
        return [f"TOML parse error: {exc}"]

    raw_hooks = data.get("hooks", [])
    errors: list[str] = []
    for i, raw in enumerate(raw_hooks):
        try:
            _parse_hook_entry(raw, i)
        except ValueError as exc:
            errors.append(str(exc))

    return errors


def match_hooks(
    hooks: tuple[HookConfig, ...],
    event: HookEvent,
    timing: HookTiming,
    workspace_name: str | None,
) -> tuple[HookConfig, ...]:
    """Filter hooks matching event/timing/workspace. Globals before workspace-scoped."""
    globals_: list[HookConfig] = []
    scoped: list[HookConfig] = []

    for h in hooks:
        if not h.enabled:
            continue
        if h.event != event:
            continue
        if h.timing != timing:
            continue
        if h.workspace is None:
            globals_.append(h)
        elif h.workspace == workspace_name:
            scoped.append(h)

    return tuple(globals_ + scoped)


def _serialize_entity(entity: object) -> dict | None:
    """Convert an entity to a plain dict, applying description truncation.

    Returns a fresh dict — the input is never mutated or aliased.
    """
    if entity is None:
        return None
    if isinstance(entity, dict):
        result: dict = dict(entity)
    else:
        # Lazy import to avoid a cli -> hooks import cycle once service integration lands.
        from .cli import to_dict

        converted = to_dict(entity)
        if not isinstance(converted, dict):
            return converted  # type: ignore[return-value]
        result = converted

    desc = result.get("description")
    if isinstance(desc, str) and len(desc.encode("utf-8")) > DESCRIPTION_MAX_BYTES:
        truncated = desc.encode("utf-8")[:DESCRIPTION_MAX_BYTES].decode("utf-8", errors="ignore")
        result["description"] = truncated
        result["description_truncated"] = True

    return result


def build_payload(
    event: HookEvent,
    *,
    workspace_id: int | None,
    workspace_name: str | None,
    entity_type: str,
    entity_id: int | None,
    entity: object,
    changes: dict | None = None,
    proposed: dict | None = None,
    meta_key: str | None = None,
    meta_value: str | None = None,
    source_workspace: dict | None = None,
    target_workspace: dict | None = None,
    archived_task_ids: list[int] | None = None,
    archived_group_ids: list[int] | None = None,
    archived_status_ids: list[int] | None = None,
    reassigned_task_ids: list[int] | None = None,
    reassigned_to: int | None = None,
) -> str:
    """Build the JSON payload string to deliver on stdin to hook commands."""
    category = EVENT_CATEGORIES[event]
    entity_dict = _serialize_entity(entity)

    payload: dict = {
        "event": event.value,
        "timing": "post",
        "workspace_id": workspace_id,
        "workspace_name": workspace_name,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "entity": entity_dict,
    }

    if category == "created":
        payload["proposed"] = proposed
        payload["changes"] = None
    elif category == "updated":
        payload["changes"] = changes
        payload["proposed"] = None
    elif category == "archived":
        payload["changes"] = changes
        payload["proposed"] = None
        if archived_task_ids is not None:
            payload["archived_task_ids"] = archived_task_ids
        if archived_group_ids is not None:
            payload["archived_group_ids"] = archived_group_ids
        if archived_status_ids is not None:
            payload["archived_status_ids"] = archived_status_ids
        if reassigned_task_ids is not None:
            payload["reassigned_task_ids"] = reassigned_task_ids
        if reassigned_to is not None:
            payload["reassigned_to"] = reassigned_to
    elif category == "meta":
        payload["meta_key"] = meta_key
        payload["meta_value"] = meta_value
        payload["changes"] = None
        payload["proposed"] = None
    elif category == "transferred":
        payload["changes"] = changes
        payload["source_workspace"] = source_workspace
        payload["target_workspace"] = target_workspace
        payload["proposed"] = None

    return json.dumps(payload)



def fire_post_hooks(hooks: tuple[HookConfig, ...], payload_json: str) -> None:
    """Fire post-hooks as fire-and-forget subprocesses.

    Never raises. Failures (subprocess startup, broken pipe, close errors) are
    intentionally silenced — post-hooks are notifications, not control flow.
    """
    for hook in hooks:
        try:
            proc = subprocess.Popen(
                hook.command,
                shell=True,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                text=True,
                start_new_session=True,
            )
            try:
                if proc.stdin is not None:
                    proc.stdin.write(payload_json)
                    proc.stdin.close()
            except OSError:
                pass
        except Exception:
            # Swallow any Popen startup failure (OSError, PermissionError, etc.)
            # so a bad hook can't interrupt the parent operation.
            pass


def fire_hooks(
    event: HookEvent,
    *,
    workspace_id: int | None,
    workspace_name: str | None,
    entity_type: str,
    entity_id: int | None,
    entity: object,
    changes: dict | None = None,
    proposed: dict | None = None,
    meta_key: str | None = None,
    meta_value: str | None = None,
    source_workspace: dict | None = None,
    target_workspace: dict | None = None,
    archived_task_ids: list[int] | None = None,
    archived_group_ids: list[int] | None = None,
    archived_status_ids: list[int] | None = None,
    reassigned_task_ids: list[int] | None = None,
    reassigned_to: int | None = None,
    hooks_path: Path | None = None,
) -> None:
    """High-level entry: load → match → build payload → fire post-hooks."""
    hooks = load_hooks(hooks_path if hooks_path is not None else DEFAULT_HOOKS_PATH)
    matched = match_hooks(hooks, event, HookTiming.POST, workspace_name)
    if not matched:
        return

    payload_json = build_payload(
        event,
        workspace_id=workspace_id,
        workspace_name=workspace_name,
        entity_type=entity_type,
        entity_id=entity_id,
        entity=entity,
        changes=changes,
        proposed=proposed,
        meta_key=meta_key,
        meta_value=meta_value,
        source_workspace=source_workspace,
        target_workspace=target_workspace,
        archived_task_ids=archived_task_ids,
        archived_group_ids=archived_group_ids,
        archived_status_ids=archived_status_ids,
        reassigned_task_ids=reassigned_task_ids,
        reassigned_to=reassigned_to,
    )

    fire_post_hooks(matched, payload_json)


def load_event_schema() -> dict:
    """Return the parsed hook_events.schema.json shipped with the package."""
    text = importlib.resources.files("stx").joinpath("hook_events.schema.json").read_text()
    return json.loads(text)
