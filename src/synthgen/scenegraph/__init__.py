"""Lazy, pull-based scene-graph view over Blender (see knowledge/scene_graph_contexts.md).

Traversal algorithms (`traverse`) run against the SceneGraph protocol, so they work on either
backend:
  * SnapshotGraph  — offline JSON, for tests/diffing (no bpy)
  * LiveGraph      — live bpy walker (import lazily; requires Blender)
"""

from . import traverse
from .protocol import TIER_GAP, TIER_NATIVE, TIER_RECONSTRUCTED, Edge
from .backend_snapshot import SnapshotGraph

__all__ = ["traverse", "Edge", "SnapshotGraph",
           "TIER_NATIVE", "TIER_RECONSTRUCTED", "TIER_GAP"]
