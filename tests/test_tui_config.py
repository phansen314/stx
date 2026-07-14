"""tui/config.py — JSON preference load/save. Daemon-free, no Textual."""
from __future__ import annotations

import json

import pytest

from tui import config as cfg


@pytest.fixture
def xdg(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    return tmp_path / "stx" / "tui.json"


class TestLoad:
    def test_defaults_when_missing(self, xdg) -> None:
        assert cfg.load_config() == cfg.DEFAULTS

    def test_reads_valid_file(self, xdg) -> None:
        xdg.parent.mkdir(parents=True)
        xdg.write_text(json.dumps({"theme": "nord", "refresh_secs": 5}))
        assert cfg.load_config() == {"theme": "nord", "refresh_secs": 5.0}

    def test_corrupt_file_falls_back(self, xdg) -> None:
        xdg.parent.mkdir(parents=True)
        xdg.write_text("{not json")
        assert cfg.load_config() == cfg.DEFAULTS

    def test_wrong_types_ignored_per_field(self, xdg) -> None:
        xdg.parent.mkdir(parents=True)
        xdg.write_text(json.dumps({"theme": 123, "refresh_secs": "fast"}))
        assert cfg.load_config() == cfg.DEFAULTS

    def test_refresh_clamped(self, xdg) -> None:
        xdg.parent.mkdir(parents=True)
        xdg.write_text(json.dumps({"refresh_secs": 100000}))
        assert cfg.load_config()["refresh_secs"] == 3600.0
        xdg.write_text(json.dumps({"refresh_secs": 0.01}))
        assert cfg.load_config()["refresh_secs"] == 0.5

    def test_bool_refresh_rejected(self, xdg) -> None:
        # bool is an int subclass — must not be accepted as a refresh value
        xdg.parent.mkdir(parents=True)
        xdg.write_text(json.dumps({"refresh_secs": True}))
        assert cfg.load_config()["refresh_secs"] == cfg.DEFAULTS["refresh_secs"]


class TestSave:
    def test_round_trip(self, xdg) -> None:
        cfg.save_config({"theme": "gruvbox", "refresh_secs": 3.0})
        assert cfg.load_config() == {"theme": "gruvbox", "refresh_secs": 3.0}
        assert xdg.exists()

    def test_save_clamps_and_defaults_missing(self, xdg) -> None:
        cfg.save_config({"refresh_secs": 99999})  # no theme key
        written = json.loads(xdg.read_text())
        assert written["theme"] == cfg.DEFAULTS["theme"]
        assert written["refresh_secs"] == 3600.0
