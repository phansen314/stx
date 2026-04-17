from __future__ import annotations

import tempfile
from enum import StrEnum
from pathlib import Path

from .formatting import node_display_id
from .service_models import EdgeListItem

_MAX_LABEL = 30

_DOT_NODE_SHAPES: dict[str, str] = {
    "task": "box",
    "group": "folder",
    "status": "ellipse",
    "workspace": "doubleoctagon",
}

_MERMAID_RESERVED = frozenset({
    "end", "graph", "subgraph", "direction", "click", "style", "classDef",
    "class", "linkStyle", "callback",
})


class GraphFormat(StrEnum):
    dot = "dot"
    mermaid = "mermaid"


def _truncate(title: str) -> str:
    if len(title) <= _MAX_LABEL:
        return title
    return title[: _MAX_LABEL - 1] + "\u2026"


def _dot_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _dot_node_id(node_type: str, node_id: int) -> str:
    return f"{node_type}_{node_id}"


def _mermaid_node_id(node_type: str, node_id: int) -> str:
    raw = f"{node_type}_{node_id}"
    if raw.lower() in _MERMAID_RESERVED:
        return f"n_{raw}"
    return raw


def _mermaid_escape(s: str) -> str:
    return s.replace('"', "#quot;")


def _collect_nodes(
    edges: tuple[EdgeListItem, ...],
) -> dict[tuple[str, int], str]:
    nodes: dict[tuple[str, int], str] = {}
    for e in edges:
        nodes.setdefault((e.from_type, e.from_id), e.from_title)
        nodes.setdefault((e.to_type, e.to_id), e.to_title)
    return nodes


def generate_dot(edges: tuple[EdgeListItem, ...], workspace_name: str) -> str:
    nodes = _collect_nodes(edges)
    lines = [
        f'digraph "{_dot_escape(workspace_name)}" {{',
        "    rankdir=LR;",
    ]
    for (ntype, nid), title in nodes.items():
        shape = _DOT_NODE_SHAPES.get(ntype, "box")
        display = node_display_id(ntype, nid)
        label = f"{display}\\n{_dot_escape(_truncate(title))}"
        lines.append(f'    {_dot_node_id(ntype, nid)} [label="{label}", shape={shape}];')
    for e in edges:
        src = _dot_node_id(e.from_type, e.from_id)
        tgt = _dot_node_id(e.to_type, e.to_id)
        lines.append(f'    {src} -> {tgt} [label="{_dot_escape(e.kind)}"];')
    lines.append("}")
    return "\n".join(lines) + "\n"


def generate_mermaid(edges: tuple[EdgeListItem, ...], workspace_name: str) -> str:
    nodes = _collect_nodes(edges)
    lines = [
        f"%% {workspace_name}",
        "graph LR",
    ]
    for (ntype, nid), title in nodes.items():
        mid = _mermaid_node_id(ntype, nid)
        display = node_display_id(ntype, nid)
        label = f"{display}: {_mermaid_escape(_truncate(title))}"
        lines.append(f'    {mid}["{label}"]')
    for e in edges:
        src = _mermaid_node_id(e.from_type, e.from_id)
        tgt = _mermaid_node_id(e.to_type, e.to_id)
        lines.append(f"    {src} -->|{e.kind}| {tgt}")
    return "\n".join(lines) + "\n"


_GENERATORS = {
    GraphFormat.dot: generate_dot,
    GraphFormat.mermaid: generate_mermaid,
}

_SUFFIXES = {
    GraphFormat.dot: ".dot",
    GraphFormat.mermaid: ".mmd",
}


def write_graph(
    edges: tuple[EdgeListItem, ...],
    workspace_name: str,
    fmt: GraphFormat,
    output: Path | None = None,
) -> Path:
    content = _GENERATORS[fmt](edges, workspace_name)
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(content)
        return output
    fd = tempfile.NamedTemporaryFile(
        suffix=_SUFFIXES[fmt], delete=False, prefix="stx-graph-", mode="w"
    )
    fd.write(content)
    fd.close()
    return Path(fd.name)
