from __future__ import annotations

from pathlib import Path

import pytest

from stx.graph import GraphFormat, generate_dot, generate_mermaid, write_graph
from stx.service_models import EdgeListItem


def _edge(
    from_type: str = "task",
    from_id: int = 1,
    from_title: str = "Alpha",
    to_type: str = "task",
    to_id: int = 2,
    to_title: str = "Beta",
    kind: str = "blocks",
    acyclic: bool = True,
) -> EdgeListItem:
    return EdgeListItem(
        from_type=from_type,
        from_id=from_id,
        from_title=from_title,
        to_type=to_type,
        to_id=to_id,
        to_title=to_title,
        workspace_id=1,
        kind=kind,
        acyclic=acyclic,
    )


class TestGenerateDot:
    def test_basic_structure(self):
        dot = generate_dot((_edge(),), "dev")
        assert 'digraph "dev"' in dot
        assert "rankdir=LR" in dot
        assert "task_1" in dot
        assert "task_2" in dot
        assert 'label="blocks"' in dot

    def test_node_shapes(self):
        edges = (
            _edge(from_type="group", from_id=10, to_type="status", to_id=3),
        )
        dot = generate_dot(edges, "ws")
        assert "shape=folder" in dot
        assert "shape=ellipse" in dot

    def test_workspace_node_shape(self):
        edges = (_edge(from_type="workspace", from_id=1),)
        dot = generate_dot(edges, "ws")
        assert "shape=doubleoctagon" in dot

    def test_title_truncation(self):
        long_title = "A" * 60
        edges = (_edge(from_title=long_title),)
        dot = generate_dot(edges, "ws")
        assert long_title not in dot
        assert "\u2026" in dot

    def test_special_chars_escaped(self):
        edges = (_edge(from_title='say "hello"', to_title="back\\slash"),)
        dot = generate_dot(edges, "ws")
        assert r"say \"hello\"" in dot
        assert "back\\\\slash" in dot

    def test_workspace_name_escaped(self):
        dot = generate_dot((_edge(),), 'my "workspace"')
        assert r'digraph "my \"workspace\""' in dot

    def test_deduplicates_nodes(self):
        edges = (
            _edge(from_id=1, to_id=2),
            _edge(from_id=2, to_id=3, from_title="Beta", to_title="Gamma"),
        )
        dot = generate_dot(edges, "ws")
        assert dot.count("task_2 [") == 1

    def test_node_labels_include_display_id(self):
        dot = generate_dot((_edge(from_id=42),), "ws")
        assert "task-0042" in dot


class TestGenerateMermaid:
    def test_basic_structure(self):
        mmd = generate_mermaid((_edge(),), "dev")
        assert "%% dev" in mmd
        assert "graph LR" in mmd
        assert "-->|blocks|" in mmd

    def test_node_labels(self):
        mmd = generate_mermaid((_edge(from_id=5, from_title="Setup"),), "ws")
        assert "task-0005: Setup" in mmd

    def test_reserved_word_sanitized(self):
        edges = (_edge(from_type="group", from_id=1, from_title="end"),)
        mmd = generate_mermaid(edges, "ws")
        assert "n_group_1" in mmd

    def test_title_truncation(self):
        long_title = "B" * 60
        edges = (_edge(from_title=long_title),)
        mmd = generate_mermaid(edges, "ws")
        assert long_title not in mmd
        assert "\u2026" in mmd

    def test_quote_escaped(self):
        edges = (_edge(from_title='say "hi"'),)
        mmd = generate_mermaid(edges, "ws")
        assert "#quot;" in mmd
        assert '"say' not in mmd.split("\n")[3]

    def test_deduplicates_nodes(self):
        edges = (
            _edge(from_id=1, to_id=2),
            _edge(from_id=2, to_id=3, from_title="Beta", to_title="Gamma"),
        )
        mmd = generate_mermaid(edges, "ws")
        node_defs = [l for l in mmd.splitlines() if "task_2[" in l]
        assert len(node_defs) == 1


class TestWriteGraph:
    def test_writes_to_explicit_output(self, tmp_path: Path):
        out = tmp_path / "graph.dot"
        result = write_graph((_edge(),), "ws", GraphFormat.dot, output=out)
        assert result == out
        assert out.exists()
        content = out.read_text()
        assert "digraph" in content

    def test_writes_temp_file_dot(self):
        result = write_graph((_edge(),), "ws", GraphFormat.dot)
        assert result.exists()
        assert result.suffix == ".dot"
        assert "stx-graph-" in result.name
        content = result.read_text()
        assert "digraph" in content
        result.unlink()

    def test_writes_temp_file_mermaid(self):
        result = write_graph((_edge(),), "ws", GraphFormat.mermaid)
        assert result.exists()
        assert result.suffix == ".mmd"
        content = result.read_text()
        assert "graph LR" in content
        result.unlink()

    def test_creates_parent_dirs(self, tmp_path: Path):
        out = tmp_path / "sub" / "dir" / "g.dot"
        result = write_graph((_edge(),), "ws", GraphFormat.dot, output=out)
        assert result.exists()

    def test_mixed_node_types(self):
        edges = (
            _edge(from_type="group", from_id=1, to_type="task", to_id=10, kind="contains"),
            _edge(from_type="task", from_id=10, to_type="status", to_id=2, kind="enters"),
        )
        dot = generate_dot(edges, "ws")
        assert "group_1" in dot
        assert "task_10" in dot
        assert "status_2" in dot
        assert "shape=folder" in dot
        assert "shape=box" in dot
        assert "shape=ellipse" in dot
