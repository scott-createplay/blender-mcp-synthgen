"""MCP tools for scene-graph introspection — fuses bpy + LiveGraph."""

from __future__ import annotations

import json
import os
import textwrap
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP
    from synthgen.mcp.transport import TransportBackend


def _src_path() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.normpath(os.path.join(here, "..", "..", ".."))


# Same-machine assumption: the MCP server and Blender share a filesystem,
# so the server-side src/ path is valid inside Blender's Python too.
_PREAMBLE = f"""\
import sys, os, json
sys.path.insert(0, r'{_src_path()}')
"""


def register(mcp: FastMCP, get_transport) -> None:

    def _run(code: str) -> str:
        transport = get_transport()
        result = transport.execute_python(code)
        if isinstance(result, dict):
            return result.get("output", json.dumps(result))
        return str(result)

    @mcp.tool()
    def graph_nodes() -> str:
        """List all top-level nodes in the scene graph.

        Returns qualified node IDs using the synthgen addressing scheme:
        COL:<name>, OBJ:<name>, OBJ:<name>/MOD:<mod>, NG:<tree>, MAT:<mat>.
        """
        return _run(_PREAMBLE + textwrap.dedent("""\
            from synthgen.scenegraph.backend_bpy import LiveGraph
            g = LiveGraph()
            print(json.dumps(sorted(g.nodes()), indent=2))
        """))

    @mcp.tool()
    def graph_neighbors(node_id: str) -> str:
        """Get all edges connected to a node.

        Returns edges with src, dst, type, tier, and data fields.
        Use this to explore the scene graph from any node.

        Args:
            node_id: Qualified node ID (e.g. "OBJ:Cube", "MAT:Material", "NG:MyTree").
        """
        return _run(_PREAMBLE + textwrap.dedent(f"""\
            from synthgen.scenegraph.backend_bpy import LiveGraph
            g = LiveGraph()
            edges = list(g.neighbors({node_id!r}))
            print(json.dumps([
                {{"src": e.src, "dst": e.dst, "type": e.type, "tier": e.tier,
                 "state_dependent": e.state_dependent, "data": e.data}}
                for e in edges
            ], indent=2))
        """))

    @mcp.tool()
    def graph_reachable(node_id: str, edge_types: list[str] | None = None) -> str:
        """Find all nodes reachable from a starting node by following edges.

        Useful for understanding the full dependency tree of an object,
        material, or node group.

        Args:
            node_id: Starting node ID.
            edge_types: Optional list of edge types to follow (e.g. ["parent", "uses_material"]).
                       If omitted, follows all edge types.
        """
        et = repr(set(edge_types)) if edge_types else "None"
        return _run(_PREAMBLE + textwrap.dedent(f"""\
            from synthgen.scenegraph.backend_bpy import LiveGraph
            from synthgen.scenegraph.traverse import reachable
            g = LiveGraph()
            nodes = reachable(g, {node_id!r}, edge_types={et})
            print(json.dumps(sorted(nodes), indent=2))
        """))

    @mcp.tool()
    def graph_impact_set(node_id: str, edge_types: list[str] | None = None) -> str:
        """Find all nodes that would be affected if a given node changes.

        Follows edges in reverse — "if I change X, what depends on X?"
        Essential for understanding the blast radius of a modification.

        Args:
            node_id: The node you're considering changing.
            edge_types: Optional edge type filter.
        """
        et = repr(set(edge_types)) if edge_types else "None"
        return _run(_PREAMBLE + textwrap.dedent(f"""\
            from synthgen.scenegraph.backend_bpy import LiveGraph
            from synthgen.scenegraph.traverse import impact_set
            g = LiveGraph()
            nodes = impact_set(g, {node_id!r}, edge_types={et})
            print(json.dumps(sorted(nodes), indent=2))
        """))

    @mcp.tool()
    def graph_attribute_trace(attr_name: str) -> str:
        """Trace a named attribute across the GN-to-shader bridge.

        Finds all producers (GN Store Named Attribute) and consumers
        (ShaderNodeAttribute) of a named attribute, connected via tier-2
        bridge edges. Requires resolving bridges first (cooks the depsgraph).

        Args:
            attr_name: The attribute name to trace (e.g. "inst_color", "rust").
        """
        return _run(_PREAMBLE + textwrap.dedent(f"""\
            from synthgen.scenegraph.backend_bpy import LiveGraph
            from synthgen.scenegraph.traverse import attribute_trace
            g = LiveGraph()
            g.resolve_attr_bridges()
            trace = attribute_trace(g, {attr_name!r})
            print(json.dumps({{
                "attribute": {attr_name!r},
                "edges": [
                    {{"src": e.src, "dst": e.dst, "type": e.type, "tier": e.tier,
                     "data": e.data}}
                    for e in trace["edges"]
                ]
            }}, indent=2))
        """))

    @mcp.tool()
    def graph_snapshot() -> str:
        """Serialize the full scene graph to JSON for diffing or provenance.

        Returns all nodes and edges as a structured JSON document.
        """
        return _run(_PREAMBLE + textwrap.dedent("""\
            from synthgen.scenegraph.backend_bpy import LiveGraph
            g = LiveGraph()
            nodes = sorted(g.nodes())
            edges = []
            for nid in nodes:
                for e in g.neighbors(nid):
                    edges.append({"src": e.src, "dst": e.dst, "type": e.type,
                                   "tier": e.tier, "data": e.data})
            print(json.dumps({"nodes": nodes, "edges": edges}, indent=2))
        """))
