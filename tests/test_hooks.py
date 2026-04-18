"""Tests for the hooks engine foundation (task 157).

Covers: config loading, matching, payload building, execution, event categories,
and schema conformance. No service or CLI integration.
"""
from __future__ import annotations

import dataclasses
import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

jsonschema = pytest.importorskip("jsonschema")

from stx.hooks import (
    DEFAULT_HOOKS_PATH,
    DESCRIPTION_MAX_BYTES,
    EVENT_CATEGORIES,
    HookConfig,
    HookEvent,
    _parse_hook_entry,
    _serialize_entity,
    build_payload,
    fire_hooks,
    fire_post_hooks,
    load_event_schema,
    load_hooks,
    match_hooks,
    validate_hooks_config,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_hooks(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "hooks.toml"
    p.write_text(content)
    return p


def _minimal_hook(
    event: str = "task.created",
    command: str = "echo hi",
    **kwargs: object,
) -> str:
    extra = ""
    for k, v in kwargs.items():
        if isinstance(v, str):
            extra += f'\n{k} = "{v}"'
        elif isinstance(v, bool):
            extra += f"\n{k} = {str(v).lower()}"
    return f'[[hooks]]\nevent = "{event}"\ncommand = "{command}"{extra}\n'


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

class TestLoadHooks:
    def test_missing_file_returns_empty(self, tmp_path: Path) -> None:
        result = load_hooks(tmp_path / "nonexistent.toml")
        assert result == ()

    def test_empty_file_returns_empty(self, tmp_path: Path) -> None:
        p = _write_hooks(tmp_path, "")
        assert load_hooks(p) == ()

    def test_empty_hooks_array_returns_empty(self, tmp_path: Path) -> None:
        p = _write_hooks(tmp_path, "hooks = []\n")
        assert load_hooks(p) == ()

    def test_valid_minimal_hook(self, tmp_path: Path) -> None:
        p = _write_hooks(tmp_path, _minimal_hook())
        hooks = load_hooks(p)
        assert len(hooks) == 1
        assert hooks[0].event == HookEvent.TASK_CREATED
        assert hooks[0].command == "echo hi"

    def test_defaults_applied(self, tmp_path: Path) -> None:
        p = _write_hooks(tmp_path, _minimal_hook())
        h = load_hooks(p)[0]
        assert h.enabled is True
        assert h.workspace is None
        assert h.name is None

    def test_explicit_fields_parsed(self, tmp_path: Path) -> None:
        p = _write_hooks(tmp_path, _minimal_hook(
            workspace="myws", name="my-hook", enabled=False
        ))
        h = load_hooks(p)[0]
        assert h.workspace == "myws"
        assert h.name == "my-hook"
        assert h.enabled is False

    def test_multiple_hooks_preserve_order(self, tmp_path: Path) -> None:
        content = _minimal_hook("task.created", "first") + \
                  _minimal_hook("task.updated", "second")
        p = _write_hooks(tmp_path, content)
        hooks = load_hooks(p)
        assert len(hooks) == 2
        assert hooks[0].command == "first"
        assert hooks[1].command == "second"

    def test_pre_timing_raises_migration_error(self, tmp_path: Path) -> None:
        p = _write_hooks(tmp_path, '[[hooks]]\nevent = "task.created"\ntiming = "pre"\ncommand = "x"\n')
        with pytest.raises(ValueError, match="timing='pre' is no longer supported"):
            load_hooks(p)

    def test_timing_absent_is_valid(self, tmp_path: Path) -> None:
        p = _write_hooks(tmp_path, '[[hooks]]\nevent = "task.created"\ncommand = "x"\n')
        hooks = load_hooks(p)
        assert len(hooks) == 1

    def test_timing_post_silently_ignored(self, tmp_path: Path) -> None:
        p = _write_hooks(tmp_path, '[[hooks]]\nevent = "task.created"\ntiming = "post"\ncommand = "x"\n')
        hooks = load_hooks(p)
        assert len(hooks) == 1

    def test_missing_event_raises(self, tmp_path: Path) -> None:
        p = _write_hooks(tmp_path, '[[hooks]]\ncommand = "x"\n')
        with pytest.raises(ValueError, match="missing required field 'event'"):
            load_hooks(p)

    def test_missing_command_raises(self, tmp_path: Path) -> None:
        p = _write_hooks(tmp_path, '[[hooks]]\nevent = "task.created"\n')
        with pytest.raises(ValueError, match="missing required field 'command'"):
            load_hooks(p)

    def test_invalid_event_raises(self, tmp_path: Path) -> None:
        p = _write_hooks(tmp_path, '[[hooks]]\nevent = "bogus.event"\ncommand = "x"\n')
        with pytest.raises(ValueError, match="invalid event 'bogus.event'"):
            load_hooks(p)

    def test_explicit_path_arg(self, tmp_path: Path) -> None:
        p = tmp_path / "custom.toml"
        p.write_text(_minimal_hook())
        hooks = load_hooks(p)
        assert len(hooks) == 1

    def test_aggregates_multiple_errors(self, tmp_path: Path) -> None:
        content = (
            '[[hooks]]\ncommand = "x"\n'
            '[[hooks]]\nevent = "task.created"\ncommand = "x"\n'
        )
        p = _write_hooks(tmp_path, content)
        with pytest.raises(ValueError) as exc_info:
            load_hooks(p)
        msg = str(exc_info.value)
        assert "hooks[0]" in msg
        assert "hooks[1]" in msg

    @pytest.mark.parametrize("toml_line,field_name", [
        ("workspace = 1", "workspace"),
        ("name = 1", "name"),
        ('enabled = "yes"', "enabled"),
    ])
    def test_invalid_field_type_raises(
        self, tmp_path: Path, toml_line: str, field_name: str
    ) -> None:
        content = (
            f'[[hooks]]\nevent = "task.created"\n'
            f'command = "x"\n{toml_line}\n'
        )
        p = _write_hooks(tmp_path, content)
        with pytest.raises(ValueError, match=f"'{field_name}'"):
            load_hooks(p)


class TestValidateHooksConfig:
    def test_valid_config_returns_empty_list(self, tmp_path: Path) -> None:
        p = _write_hooks(tmp_path, _minimal_hook())
        assert validate_hooks_config(p) == []

    def test_missing_file_returns_empty_list(self, tmp_path: Path) -> None:
        assert validate_hooks_config(tmp_path / "gone.toml") == []

    def test_toml_parse_error_surfaces(self, tmp_path: Path) -> None:
        p = _write_hooks(tmp_path, "[[hooks]\nbad toml")
        errors = validate_hooks_config(p)
        assert len(errors) == 1
        assert "TOML parse error" in errors[0]

    def test_multiple_errors_all_returned(self, tmp_path: Path) -> None:
        content = (
            '[[hooks]]\ncommand = "x"\n'
            '[[hooks]]\nevent = "bogus.event"\ncommand = "x"\n'
        )
        p = _write_hooks(tmp_path, content)
        errors = validate_hooks_config(p)
        assert len(errors) == 2


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------

class TestMatchHooks:
    def _hooks(self) -> tuple[HookConfig, ...]:
        return (
            HookConfig(HookEvent.TASK_CREATED, "global-post"),
            HookConfig(HookEvent.TASK_CREATED, "ws-a-post", workspace="ws-a"),
            HookConfig(HookEvent.TASK_UPDATED, "update-post"),
            HookConfig(HookEvent.TASK_CREATED, "disabled", enabled=False),
        )

    def test_filters_by_event(self) -> None:
        result = match_hooks(self._hooks(), HookEvent.TASK_UPDATED, None)
        assert len(result) == 1
        assert result[0].command == "update-post"

    def test_workspace_scoped_matches_named_workspace(self) -> None:
        result = match_hooks(self._hooks(), HookEvent.TASK_CREATED, "ws-a")
        commands = [h.command for h in result]
        assert "ws-a-post" in commands

    def test_global_matches_any_workspace(self) -> None:
        result = match_hooks(self._hooks(), HookEvent.TASK_CREATED, "other-ws")
        commands = [h.command for h in result]
        assert "global-post" in commands
        assert "ws-a-post" not in commands

    def test_disabled_hooks_skipped(self) -> None:
        result = match_hooks(self._hooks(), HookEvent.TASK_CREATED, None)
        assert all(h.command != "disabled" for h in result)

    def test_globals_before_workspace_scoped(self) -> None:
        result = match_hooks(self._hooks(), HookEvent.TASK_CREATED, "ws-a")
        commands = [h.command for h in result]
        assert commands.index("global-post") < commands.index("ws-a-post")

    def test_empty_hooks_returns_empty(self) -> None:
        assert match_hooks((), HookEvent.TASK_CREATED, None) == ()


# ---------------------------------------------------------------------------
# Payload building
# ---------------------------------------------------------------------------

@dataclasses.dataclass(frozen=True)
class _FakeTask:
    id: int
    title: str
    description: str | None = None
    workspace_id: int = 1
    status_id: int = 1
    priority: int = 1
    due_date: int | None = None
    archived: bool = False
    created_at: int = 0
    start_date: int | None = None
    finish_date: int | None = None
    group_id: int | None = None
    metadata: dict = dataclasses.field(default_factory=dict)
    done: bool = False
    version: int = 0


@dataclasses.dataclass(frozen=True)
class _FakeGroup:
    id: int
    title: str
    workspace_id: int = 1
    description: str | None = None
    parent_id: int | None = None
    archived: bool = False
    created_at: int = 0
    metadata: dict = dataclasses.field(default_factory=dict)
    done: bool = False
    version: int = 0


@dataclasses.dataclass(frozen=True)
class _FakeWorkspace:
    id: int
    name: str
    archived: bool = False
    created_at: int = 0
    metadata: dict = dataclasses.field(default_factory=dict)
    version: int = 0


@dataclasses.dataclass(frozen=True)
class _FakeStatus:
    id: int
    name: str
    workspace_id: int = 1
    archived: bool = False
    created_at: int = 0
    is_terminal: bool = False
    version: int = 0


class TestBuildPayload:
    def _created_payload(self, entity: object = None, proposed: dict | None = None) -> dict:
        raw = build_payload(
            HookEvent.TASK_CREATED,
            workspace_id=1,
            workspace_name="ws",
            entity_type="task",
            entity_id=1,
            entity=entity,
            proposed=proposed,
        )
        return json.loads(raw)

    def test_created_envelope(self) -> None:
        p = self._created_payload()
        assert p["event"] == "task.created"
        assert "timing" not in p
        assert p["workspace_id"] == 1
        assert p["workspace_name"] == "ws"
        assert p["entity_type"] == "task"
        assert p["entity_id"] == 1

    def test_created_has_null_changes(self) -> None:
        p = self._created_payload(proposed={"title": "foo"})
        assert p["changes"] is None
        assert p["proposed"] == {"title": "foo"}

    def test_updated_has_null_proposed(self) -> None:
        raw = build_payload(
            HookEvent.TASK_UPDATED,
            workspace_id=1,
            workspace_name="ws",
            entity_type="task",
            entity_id=1,
            entity={"id": 1},
            changes={"title": {"old": "a", "new": "b"}},
        )
        p = json.loads(raw)
        assert p["proposed"] is None
        assert p["changes"] == {"title": {"old": "a", "new": "b"}}

    def test_meta_payload_fields(self) -> None:
        raw = build_payload(
            HookEvent.TASK_META_SET,
            workspace_id=1,
            workspace_name="ws",
            entity_type="task",
            entity_id=5,
            entity={"id": 5},
            meta_key="priority",
            meta_value="high",
        )
        p = json.loads(raw)
        assert p["meta_key"] == "priority"
        assert p["meta_value"] == "high"
        assert p["changes"] is None
        assert p["proposed"] is None

    def test_description_truncation(self) -> None:
        long_desc = "x" * (DESCRIPTION_MAX_BYTES + 100)
        task = _FakeTask(id=1, title="t", description=long_desc)
        raw = build_payload(
            HookEvent.TASK_UPDATED,
            workspace_id=1,
            workspace_name="ws",
            entity_type="task",
            entity_id=1,
            entity=task,
            changes={},
        )
        p = json.loads(raw)
        assert p["entity"]["description_truncated"] is True
        assert len(p["entity"]["description"].encode("utf-8")) <= DESCRIPTION_MAX_BYTES

    def test_description_not_truncated_within_limit(self) -> None:
        task = _FakeTask(id=1, title="t", description="short")
        raw = build_payload(
            HookEvent.TASK_UPDATED,
            workspace_id=1,
            workspace_name="ws",
            entity_type="task",
            entity_id=1,
            entity=task,
            changes={},
        )
        p = json.loads(raw)
        assert "description_truncated" not in p["entity"]


class TestSerializeEntity:
    def test_none_returns_none(self) -> None:
        assert _serialize_entity(None) is None

    def test_dict_returns_fresh_copy(self) -> None:
        d = {"from_type": "task", "to_type": "group", "kind": "blocks"}
        result = _serialize_entity(d)
        assert result is not d
        assert result == d

    def test_dataclass_converted(self) -> None:
        task = _FakeTask(id=7, title="hello")
        result = _serialize_entity(task)
        assert isinstance(result, dict)
        assert result["id"] == 7
        assert result["title"] == "hello"

    def test_unicode_description_truncated_by_bytes(self) -> None:
        # Each '€' is 3 bytes in UTF-8
        euro_count = (DESCRIPTION_MAX_BYTES // 3) + 10
        long_desc = "€" * euro_count
        d = {"description": long_desc}
        result = _serialize_entity(d)
        assert result is not None
        assert len(result["description"].encode("utf-8")) <= DESCRIPTION_MAX_BYTES
        assert result.get("description_truncated") is True


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


class TestFirePostHooks:
    def _hook(self) -> HookConfig:
        return HookConfig(HookEvent.TASK_CREATED, "echo")

    def test_popen_called_with_shell_true(self) -> None:
        mock_proc = MagicMock()
        mock_proc.stdin = MagicMock()
        with patch("stx.hooks.subprocess.Popen", return_value=mock_proc) as mock_popen:
            fire_post_hooks((self._hook(),), "{}")
        _, kwargs = mock_popen.call_args
        assert kwargs.get("shell") is True

    def test_stdin_write_oserror_swallowed(self) -> None:
        mock_proc = MagicMock()
        mock_proc.stdin.write.side_effect = OSError("broken")
        with patch("stx.hooks.subprocess.Popen", return_value=mock_proc):
            fire_post_hooks((self._hook(),), "{}")  # must not raise

    def test_no_raise_on_nonzero(self) -> None:
        mock_proc = MagicMock()
        mock_proc.stdin = MagicMock()
        mock_proc.returncode = 1
        with patch("stx.hooks.subprocess.Popen", return_value=mock_proc):
            fire_post_hooks((self._hook(),), "{}")  # must not raise

    def test_popen_oserror_swallowed(self) -> None:
        with patch("stx.hooks.subprocess.Popen", side_effect=OSError("no exec")):
            fire_post_hooks((self._hook(),), "{}")  # must not raise


class TestFireHooks:
    def test_no_config_file_is_noop(self, tmp_path: Path) -> None:
        with patch("stx.hooks.fire_post_hooks") as mock_post:
            fire_hooks(
                HookEvent.TASK_CREATED,
                workspace_id=1, workspace_name="ws",
                entity_type="task", entity_id=1, entity=None,
                hooks_path=tmp_path / "nonexistent.toml",
            )
        mock_post.assert_not_called()

    def test_matching_post_hooks_calls_fire_post_hooks(self, tmp_path: Path) -> None:
        p = _write_hooks(tmp_path, _minimal_hook())
        with patch("stx.hooks.fire_post_hooks") as mock_post:
            fire_hooks(
                HookEvent.TASK_CREATED,
                workspace_id=1, workspace_name="ws",
                entity_type="task", entity_id=1, entity=None,
                hooks_path=p,
            )
        mock_post.assert_called_once()


# ---------------------------------------------------------------------------
# Event categories
# ---------------------------------------------------------------------------

class TestEventCategories:
    def test_all_events_have_category(self) -> None:
        for event in HookEvent:
            assert event in EVENT_CATEGORIES, f"{event} missing from EVENT_CATEGORIES"

    def test_all_category_values_are_valid(self) -> None:
        valid = {"created", "updated", "archived", "meta", "transferred"}
        for event, category in EVENT_CATEGORIES.items():
            assert category in valid, f"{event}: unexpected category '{category}'"

    @pytest.mark.parametrize("event,expected", [
        (HookEvent.TASK_CREATED, "created"),
        (HookEvent.GROUP_CREATED, "created"),
        (HookEvent.STATUS_CREATED, "created"),
        (HookEvent.EDGE_CREATED, "created"),
        (HookEvent.TASK_UPDATED, "updated"),
        (HookEvent.TASK_MOVED, "updated"),
        (HookEvent.TASK_DONE, "updated"),
        (HookEvent.TASK_UNDONE, "updated"),
        (HookEvent.TASK_ASSIGNED, "updated"),
        (HookEvent.TASK_ARCHIVED, "archived"),
        (HookEvent.GROUP_ARCHIVED, "archived"),
        (HookEvent.TASK_META_SET, "meta"),
        (HookEvent.GROUP_META_SET, "meta"),
        (HookEvent.WORKSPACE_META_REMOVED, "meta"),
        (HookEvent.TASK_TRANSFERRED, "transferred"),
    ])
    def test_category_mapping(self, event: HookEvent, expected: str) -> None:
        assert EVENT_CATEGORIES[event] == expected


# ---------------------------------------------------------------------------
# Schema conformance
# ---------------------------------------------------------------------------

def _full_task_entity() -> dict:
    return _serialize_entity(_FakeTask(id=1, title="t"))  # type: ignore[return-value]


def _full_group_entity() -> dict:
    return _serialize_entity(_FakeGroup(id=1, title="g"))  # type: ignore[return-value]


def _full_workspace_entity() -> dict:
    return _serialize_entity(_FakeWorkspace(id=1, name="ws"))  # type: ignore[return-value]


def _full_status_entity() -> dict:
    return _serialize_entity(_FakeStatus(id=1, name="todo"))  # type: ignore[return-value]


def _full_edge_entity() -> dict:
    return {
        "from_type": "task", "from_id": 1,
        "to_type": "task", "to_id": 2,
        "workspace_id": 1, "kind": "blocks",
        "acyclic": True, "metadata": {},
        "archived": False, "version": 0,
    }


# (event, entity_type_name, entity_factory) — for parametrized conformance tests.
_CREATED_CASES = [
    (HookEvent.TASK_CREATED, "task", _full_task_entity),
    (HookEvent.GROUP_CREATED, "group", _full_group_entity),
    (HookEvent.WORKSPACE_CREATED, "workspace", _full_workspace_entity),
    (HookEvent.STATUS_CREATED, "status", _full_status_entity),
    (HookEvent.EDGE_CREATED, "edge", _full_edge_entity),
]

_UPDATED_CASES = [
    (HookEvent.TASK_UPDATED, "task", _full_task_entity, {"title": {"old": "a", "new": "b"}}),
    (HookEvent.GROUP_UPDATED, "group", _full_group_entity, {"title": {"old": "a", "new": "b"}}),
    (HookEvent.WORKSPACE_UPDATED, "workspace", _full_workspace_entity, {"name": {"old": "a", "new": "b"}}),
    (HookEvent.STATUS_UPDATED, "status", _full_status_entity, {"name": {"old": "a", "new": "b"}}),
    (HookEvent.EDGE_UPDATED, "edge", _full_edge_entity, {"acyclic": {"old": False, "new": True}}),
]

_ARCHIVED_CASES = [
    (HookEvent.TASK_ARCHIVED, "task", _full_task_entity),
    (HookEvent.GROUP_ARCHIVED, "group", _full_group_entity),
    (HookEvent.WORKSPACE_ARCHIVED, "workspace", _full_workspace_entity),
    (HookEvent.STATUS_ARCHIVED, "status", _full_status_entity),
    (HookEvent.EDGE_ARCHIVED, "edge", _full_edge_entity),
]

_BULK_ARCHIVED_CASES = [
    (
        HookEvent.STATUS_ARCHIVED, "status", _full_status_entity,
        {"archived_task_ids": [1, 2, 3]},
        "status_force",
    ),
    (
        HookEvent.STATUS_ARCHIVED, "status", _full_status_entity,
        {"reassigned_task_ids": [4, 5], "reassigned_to": 7},
        "status_reassign",
    ),
    (
        HookEvent.GROUP_ARCHIVED, "group", _full_group_entity,
        {"archived_task_ids": [1, 2], "archived_group_ids": [10, 11]},
        "group_cascade",
    ),
    (
        HookEvent.WORKSPACE_ARCHIVED, "workspace", _full_workspace_entity,
        {"archived_task_ids": [1], "archived_group_ids": [2], "archived_status_ids": [3]},
        "workspace_cascade",
    ),
]

_META_CASES = [
    (HookEvent.TASK_META_SET, "task", _full_task_entity),
    (HookEvent.GROUP_META_SET, "group", _full_group_entity),
    (HookEvent.WORKSPACE_META_SET, "workspace", _full_workspace_entity),
    (HookEvent.EDGE_META_SET, "edge", _full_edge_entity),
]


class TestSchemaConformance:
    def test_schema_loads(self) -> None:
        schema = load_event_schema()
        assert isinstance(schema, dict)
        assert "$schema" in schema

    def test_schema_valid_draft_2020_12(self) -> None:
        schema = load_event_schema()
        jsonschema.Draft202012Validator.check_schema(schema)

    def test_all_events_in_schema(self) -> None:
        schema = load_event_schema()
        event_enum = schema["$defs"]["eventEnum"]["enum"]
        for event in HookEvent:
            assert event.value in event_enum, f"{event.value} missing from schema event enum"

    def test_payload_matches_schema_created(self) -> None:
        schema = load_event_schema()
        payload = json.loads(build_payload(
            HookEvent.TASK_CREATED,
            workspace_id=1,
            workspace_name="test",
            entity_type="task",
            entity_id=1,
            entity=None,
            proposed={"title": "new task"},
        ))
        _validate_payload(schema, payload)

    def test_payload_matches_schema_updated(self) -> None:
        schema = load_event_schema()
        payload = json.loads(build_payload(
            HookEvent.TASK_UPDATED,
            workspace_id=1,
            workspace_name="test",
            entity_type="task",
            entity_id=1,
            entity=_full_task_entity(),
            changes={"title": {"old": "a", "new": "b"}},
        ))
        _validate_payload(schema, payload)

    def test_payload_matches_schema_meta(self) -> None:
        schema = load_event_schema()
        payload = json.loads(build_payload(
            HookEvent.TASK_META_SET,
            workspace_id=1,
            workspace_name="test",
            entity_type="task",
            entity_id=1,
            entity=_full_task_entity(),
            meta_key="tag",
            meta_value="urgent",
        ))
        _validate_payload(schema, payload)

    @pytest.mark.parametrize(
        "event,entity_type,entity_factory",
        _CREATED_CASES,
        ids=[c[1] for c in _CREATED_CASES],
    )
    def test_created_payload_all_entities(
        self, event: HookEvent, entity_type: str, entity_factory: object
    ) -> None:
        schema = load_event_schema()
        payload = json.loads(build_payload(
            event,
            workspace_id=1, workspace_name="ws",
            entity_type=entity_type, entity_id=1,
            entity=entity_factory(),  # type: ignore[misc]
            proposed={"k": "v"},
        ))
        _validate_payload(schema, payload)

    @pytest.mark.parametrize(
        "event,entity_type,entity_factory,changes",
        _UPDATED_CASES,
        ids=[c[1] for c in _UPDATED_CASES],
    )
    def test_updated_payload_all_entities(
        self, event: HookEvent, entity_type: str,
        entity_factory: object, changes: dict,
    ) -> None:
        schema = load_event_schema()
        payload = json.loads(build_payload(
            event,
            workspace_id=1, workspace_name="ws",
            entity_type=entity_type, entity_id=1,
            entity=entity_factory(),  # type: ignore[misc]
            changes=changes,
        ))
        _validate_payload(schema, payload)

    @pytest.mark.parametrize(
        "event,entity_type,entity_factory",
        _ARCHIVED_CASES,
        ids=[c[1] for c in _ARCHIVED_CASES],
    )
    def test_archived_payload_all_entities(
        self, event: HookEvent, entity_type: str, entity_factory: object
    ) -> None:
        schema = load_event_schema()
        payload = json.loads(build_payload(
            event,
            workspace_id=1, workspace_name="ws",
            entity_type=entity_type, entity_id=1,
            entity=entity_factory(),  # type: ignore[misc]
            changes={"archived": {"old": False, "new": True}},
        ))
        _validate_payload(schema, payload)

    @pytest.mark.parametrize(
        "event,entity_type,entity_factory",
        _META_CASES,
        ids=[c[1] for c in _META_CASES],
    )
    def test_meta_payload_all_entities(
        self, event: HookEvent, entity_type: str, entity_factory: object
    ) -> None:
        schema = load_event_schema()
        payload = json.loads(build_payload(
            event,
            workspace_id=1, workspace_name="ws",
            entity_type=entity_type, entity_id=1,
            entity=entity_factory(),  # type: ignore[misc]
            meta_key="tag", meta_value="v",
        ))
        _validate_payload(schema, payload)

    @pytest.mark.parametrize(
        "event,entity_type,entity_factory,extras,_id",
        _BULK_ARCHIVED_CASES,
        ids=[c[4] for c in _BULK_ARCHIVED_CASES],
    )
    def test_bulk_archived_payload_schema(
        self,
        event: HookEvent,
        entity_type: str,
        entity_factory: object,
        extras: dict,
        _id: str,
    ) -> None:
        schema = load_event_schema()
        payload = json.loads(build_payload(
            event,
            workspace_id=1, workspace_name="ws",
            entity_type=entity_type, entity_id=1,
            entity=entity_factory(),  # type: ignore[misc]
            changes={"archived": {"old": False, "new": True}},
            **extras,
        ))
        _validate_payload(schema, payload)
        for key, val in extras.items():
            assert payload[key] == val

    def test_schema_rejects_garbage_entity(self) -> None:
        schema = load_event_schema()
        payload = json.loads(build_payload(
            HookEvent.TASK_UPDATED,
            workspace_id=1,
            workspace_name="test",
            entity_type="task",
            entity_id=1,
            entity={"garbage": True},
            changes={},
        ))
        validator = jsonschema.Draft202012Validator(schema)
        errors = list(validator.iter_errors(payload))
        assert errors, "Schema should reject a payload with a garbage entity"


def _validate_payload(schema: dict, payload: dict) -> None:
    validator = jsonschema.Draft202012Validator(schema)
    errors = list(validator.iter_errors(payload))
    assert not errors, f"Schema validation errors: {[str(e) for e in errors]}"
