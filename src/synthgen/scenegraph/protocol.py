"""Scene-graph protocol — the backend-agnostic interface.

The graph is a **lazy, pull-based view** over the scene (see
knowledge/scene_graph_contexts.md), not an ETL dump. Traversal algorithms
(traverse.py) are written against this Protocol so they run identically on:

  * a live bpy backend  (backend_bpy.py, Phase 2) — always current, queries on demand
  * a snapshot backend  (backend_snapshot.py)     — offline JSON, for diffing

Nothing here imports bpy — it stays importable and testable without Blender.

Node ids are stable qualified paths (the addressing scheme that makes refactor possible):
    OBJ:<obj> / MOD:<mod> / NG:<tree> / NODE:<node> / SOCK_IN:<identifier>
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterator, Optional, Protocol

# Edge tiers (see spec): 1 native pointer, 2 reconstructed (name/index, cook-then-read),
# 3 ontological gap (recorded, never fabricated).
TIER_NATIVE = 1
TIER_RECONSTRUCTED = 2
TIER_GAP = 3


@dataclass(frozen=True)
class Edge:
    src: str
    dst: str
    type: str                      # e.g. "modifier_uses_tree", "attr_bridge", "drives"
    tier: int = TIER_NATIVE
    state_dependent: bool = False  # tier-2 edges are snapshot-valid, not structural
    resolved: bool = True          # false => dynamic/ambiguous, could not be resolved
    data: dict = field(default_factory=dict)


class SceneGraph(Protocol):
    """A backend yields the graph lazily. Implementations must provide these."""

    def nodes(self) -> Iterator[str]:
        """Yield known node ids (may be lazy / partial for live backends)."""
        ...

    def resolve(self, node_id: str) -> Optional[dict]:
        """Return node detail (kind + properties) on demand, or None if unknown."""

    def neighbors(self, node_id: str, edge_types: Optional[set] = None) -> Iterator[Edge]:
        """Yield outgoing edges from node_id, optionally filtered by edge type.

        This is the single primitive every traversal is built on. Live backends
        compute edges by querying bpy here (pull-based cooking); the snapshot
        backend reads them from a materialized dict.
        """
