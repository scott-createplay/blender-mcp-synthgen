"""Snapshot backend — SceneGraph over a materialized JSON dict. No bpy; offline-testable.

This is the `materialize(walk(all))` projection of the live walker: same protocol, read from a
static document. Used for offline analysis, diffing two scene states, and testing the traversal
algorithms against fixtures without Blender.

Document shape (see knowledge/scene_graph_contexts.md):
    { "nodes": [ {"id","kind","data"} ... ],
      "edges": [ {"src","dst","type","tier","state_dependent","resolved","data"} ... ] }
"""

from __future__ import annotations

import json
from typing import Iterator, Optional

from .protocol import Edge


class SnapshotGraph:
    def __init__(self, doc: dict):
        self._nodes = {n["id"]: n for n in doc.get("nodes", [])}
        self._out: dict = {}
        for e in doc.get("edges", []):
            edge = Edge(
                src=e["src"], dst=e["dst"], type=e["type"],
                tier=e.get("tier", 1),
                state_dependent=e.get("state_dependent", False),
                resolved=e.get("resolved", True),
                data=e.get("data", {}) or {},
            )
            self._out.setdefault(edge.src, []).append(edge)
            # endpoints referenced only by edges still count as (bare) nodes
            self._nodes.setdefault(edge.src, {"id": edge.src})
            self._nodes.setdefault(edge.dst, {"id": edge.dst})

    @classmethod
    def from_file(cls, path: str) -> "SnapshotGraph":
        with open(path, "r", encoding="utf-8") as f:
            return cls(json.load(f))

    def nodes(self) -> Iterator[str]:
        return iter(self._nodes)

    def resolve(self, node_id: str) -> Optional[dict]:
        return self._nodes.get(node_id)

    def neighbors(self, node_id: str, edge_types: Optional[set] = None) -> Iterator[Edge]:
        for e in self._out.get(node_id, ()):
            if edge_types is None or e.type in edge_types:
                yield e
