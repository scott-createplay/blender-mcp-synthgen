"""MCP tools wrapping synthgen.schema.query — grounded node lookup."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from synthgen.schema.query import (
    data_find, data_show, data_socket, data_setting, load_schema,
)

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


_VALID_TREE_TYPES = {"gn", "shader", "compositor"}


def register(mcp: FastMCP, get_blender_dir=None) -> None:

    def _load_nodes(tree_type: str) -> dict:
        if tree_type not in _VALID_TREE_TYPES:
            raise ValueError(
                f"Invalid tree_type {tree_type!r}. "
                f"Must be one of: {', '.join(sorted(_VALID_TREE_TYPES))}"
            )
        blender_dir = get_blender_dir() if get_blender_dir else None
        schema, _ = load_schema(tree_type, blender_dir=blender_dir)
        return schema["nodes"]
    @mcp.tool()
    def schema_find(substring: str, tree_type: str = "gn") -> str:
        """Query the grounded schema before authoring nodes. Socket label != identifier —
        always use identifiers from this tool.

        Find Blender nodes whose type ID or label matches a substring.

        Grounded against extracted Blender schemas — returns real node identifiers,
        not guesses. Use this before creating nodes to get the correct type ID.

        Args:
            substring: Text to search for in node IDs and labels.
            tree_type: Which node tree schema to search: "gn", "shader", or "compositor".
        """
        nodes = _load_nodes(tree_type)
        results = data_find(nodes, substring)
        return json.dumps({"results": results, "count": len(results)})

    @mcp.tool()
    def schema_show(node: str, tree_type: str = "gn") -> str:
        """Inspect node details before wiring. Socket label != identifier — use
        identifiers returned here.

        Show full details for a Blender node type: all sockets (with identifiers,
        not labels), settings, and their defaults.

        IMPORTANT: Socket identifiers are what you use in code. Socket labels are
        display names only — they may differ from identifiers. This tool shows both.

        Args:
            node: Node type ID (e.g. "GeometryNodeDistributePointsOnFaces") or label.
            tree_type: Which schema: "gn", "shader", or "compositor".
        """
        nodes = _load_nodes(tree_type)
        result = data_show(nodes, node)
        return json.dumps({"node": result})

    @mcp.tool()
    def schema_socket(substring: str, tree_type: str = "gn") -> str:
        """Look up socket details before linking. The identifier is what Blender
        uses internally, not the display label.

        Find nodes that have a socket matching a substring.

        Useful when you know the socket name but not which node has it.

        Args:
            substring: Text to search for in socket names and identifiers.
            tree_type: Which schema: "gn", "shader", or "compositor".
        """
        nodes = _load_nodes(tree_type)
        results = data_socket(nodes, substring)
        return json.dumps({"results": results, "count": len(results)})

    @mcp.tool()
    def schema_setting(substring: str, tree_type: str = "gn") -> str:
        """Verify setting names before set_node_property. Use the exact names
        returned here.

        Find nodes that have an enum setting matching a substring.

        Useful for finding nodes with domain, data_type, or other enum controls.

        Args:
            substring: Text to search in setting names (e.g. "domain", "data_type").
            tree_type: Which schema: "gn", "shader", or "compositor".
        """
        nodes = _load_nodes(tree_type)
        results = data_setting(nodes, substring)
        return json.dumps({"results": results, "count": len(results)})
