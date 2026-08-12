"""Traversal algorithms over the SceneGraph protocol (backend-agnostic).

These use only `neighbors()` / `nodes()` from protocol.py, so they run identically on the live
bpy backend and the offline snapshot backend. Forward traversals need only `neighbors()`;
reverse ones (`impact_set`, `ancestors`) build a reverse index and therefore need an
enumerable `nodes()` — fine for the snapshot backend and for a bounded live neighborhood.
"""

from __future__ import annotations

from collections import deque
from typing import Iterable, Optional


def reachable(graph, start: str, edge_types: Optional[set] = None) -> set:
    """All node ids reachable from `start` following outgoing edges (forward closure)."""
    seen, q = {start}, deque([start])
    while q:
        cur = q.popleft()
        for e in graph.neighbors(cur, edge_types):
            if e.dst not in seen:
                seen.add(e.dst)
                q.append(e.dst)
    seen.discard(start)
    return seen


def path(graph, src: str, dst: str, edge_types: Optional[set] = None) -> Optional[list]:
    """A shortest forward edge-path src -> dst, as a list of Edge, or None."""
    prev, q = {src: None}, deque([src])
    while q:
        cur = q.popleft()
        if cur == dst:
            out, node = [], dst
            while prev[node] is not None:
                out.append(prev[node])
                node = prev[node].src
            return list(reversed(out))
        for e in graph.neighbors(cur, edge_types):
            if e.dst not in prev:
                prev[e.dst] = e
                q.append(e.dst)
    return None


def build_reverse_index(graph, node_ids: Optional[Iterable[str]] = None) -> dict:
    """Materialize dst -> [Edge] by scanning forward edges. Needs enumerable nodes()."""
    rev: dict = {}
    ids = node_ids if node_ids is not None else list(graph.nodes())
    for nid in ids:
        for e in graph.neighbors(nid):
            rev.setdefault(e.dst, []).append(e)
    return rev


def impact_set(graph, target: str, node_ids: Optional[Iterable[str]] = None) -> set:
    """Everything whose value could change if `target` changes (reverse reachability).

    "If I change this node, what breaks?" — the core refactor-safety query.
    """
    rev = build_reverse_index(graph, node_ids)
    seen, q = {target}, deque([target])
    while q:
        cur = q.popleft()
        for e in rev.get(cur, ()):
            if e.src not in seen:
                seen.add(e.src)
                q.append(e.src)
    seen.discard(target)
    return seen


def attribute_trace(graph, attr_name: str, node_ids: Optional[Iterable[str]] = None) -> dict:
    """Producers and consumers of a named attribute across the GN<->shader bridge.

    Reads tier-2 `attr_bridge` edges (see knowledge/attribute_bridge.md). Returns
    {"attr": name, "edges": [Edge...]} — dead bridges surface as producers with no
    consumer (or vice-versa).
    """
    ids = node_ids if node_ids is not None else list(graph.nodes())
    edges = [
        e
        for nid in ids
        for e in graph.neighbors(nid, {"attr_bridge"})
        if e.data.get("attr") == attr_name
    ]
    return {"attr": attr_name, "edges": edges}
