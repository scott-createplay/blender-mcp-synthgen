"""MCP tools for verification — confirm attributes, properties, and state."""

from __future__ import annotations

import json
import textwrap
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


def register(mcp: FastMCP, get_transport, get_blender_version=None) -> None:

    def _run(code: str) -> str:
        transport = get_transport()
        result = transport.execute_python(code)
        if isinstance(result, dict):
            return result.get("output", json.dumps(result))
        return str(result)

    def _ver() -> tuple[int, ...]:
        if get_blender_version:
            return get_blender_version()
        return (5, 0, 0)

    @mcp.tool()
    def verify_attribute_exists(object_name: str, attribute_name: str) -> str:
        """Validate attribute bridges at runtime. Use after wire_attr_bridge to
        confirm data flows correctly.

        Check whether a named attribute exists on an object's evaluated mesh.

        Cooks the depsgraph to get the evaluated object, then checks its
        mesh attributes. Use this after wiring a Store Named Attribute node
        to confirm the attribute is actually being produced.

        Args:
            object_name: Name of the object to check.
            attribute_name: The attribute name to look for (e.g. "inst_color").
        """
        return _run(textwrap.dedent(f"""\
            import bpy, json
            obj = bpy.data.objects.get({object_name!r})
            if not obj:
                print(json.dumps({{"exists": False, "error": "object not found: {object_name}"}}))
            elif not obj.data or not hasattr(obj.data, 'attributes'):
                print(json.dumps({{"exists": False, "error": "object has no mesh data"}}))
            else:
                dg = bpy.context.evaluated_depsgraph_get()
                eval_obj = obj.evaluated_get(dg)
                attrs = eval_obj.data.attributes
                attr = attrs.get({attribute_name!r})
                if attr:
                    print(json.dumps({{
                        "exists": True,
                        "attribute": {attribute_name!r},
                        "domain": attr.domain,
                        "data_type": attr.data_type,
                    }}))
                else:
                    available = [a.name for a in attrs]
                    print(json.dumps({{
                        "exists": False,
                        "attribute": {attribute_name!r},
                        "available": available,
                    }}))
        """))

    @mcp.tool()
    def get_modifier_inputs(
        object_name: str,
        modifier_name: str,
    ) -> str:
        """Read all input sockets of a Geometry Nodes modifier — identifier, name,
        type, and current value. Use to inspect modifier state without mutation.

        Args:
            object_name: Name of the object with the GN modifier.
            modifier_name: Name of the Geometry Nodes modifier.
        """
        from synthgen.mcp.tools.compat import emit_iter_inputs

        iter_block = emit_iter_inputs(_ver(), "mod")
        iter_indented = textwrap.indent(iter_block, "        ")

        code = textwrap.dedent(f"""\
            import bpy, json
            obj = bpy.data.objects.get({object_name!r})
            if not obj:
                print(f"ERROR: object {object_name!r} not found. Available: {{[o.name for o in bpy.data.objects]}}")
            else:
                mod = obj.modifiers.get({modifier_name!r})
                if not mod:
                    print(f"ERROR: modifier {modifier_name!r} not found on {{obj.name}}. Available: {{[m.name for m in obj.modifiers]}}")
                else:
        """) + iter_indented + textwrap.dedent(f"""\
                    print(json.dumps({{"object": {object_name!r}, "modifier": {modifier_name!r}, "inputs": inputs}}))
        """)
        return _run(code)

    @mcp.tool()
    def list_tree_nodes(
        tree_name: str,
        tree_context: str = "gn",
    ) -> str:
        """List all nodes in a node tree — names, types, and socket identifiers.
        Use before mutations (link_sockets, set_socket_default) to verify node
        names and available sockets. Cheap call — no depsgraph evaluation.

        Args:
            tree_name: Name of the node tree.
            tree_context: Where to find the tree — "gn", "shader", "compositor".
        """
        if tree_context == "shader":
            tree_lookup_lines = [
                f"_mat = bpy.data.materials.get({tree_name!r})",
                "tree = _mat.node_tree if _mat else None",
            ]
        elif tree_context == "compositor":
            from synthgen.mcp.tools.compat import emit_compositor_tree
            tree_lookup_lines = [f"tree = {emit_compositor_tree(_ver(), 'bpy.context.scene')}"]
        else:
            tree_lookup_lines = [f"tree = bpy.data.node_groups.get({tree_name!r})"]

        parts = ["import bpy, json"]
        parts.extend(tree_lookup_lines)
        parts.append("if not tree:")
        parts.append(f'    print(json.dumps({{"error": f"tree {tree_name!r} not found"}}))')
        parts.append("else:")
        parts.append("    nodes = []")
        parts.append("    for n in tree.nodes:")
        parts.append("        nodes.append({")
        parts.append('            "name": n.name,')
        parts.append('            "type": n.bl_idname,')
        parts.append('            "inputs": [s.identifier for s in n.inputs],')
        parts.append('            "outputs": [s.identifier for s in n.outputs],')
        parts.append("        })")
        parts.append('    print(json.dumps({"tree": tree.name, "node_count": len(nodes), "nodes": nodes}))')

        return _run("\n".join(parts))

    @mcp.tool()
    def evaluate_object(object_name: str) -> str:
        """Evaluate an object through the depsgraph and return its mesh stats,
        attributes, and modifier warnings. One call replaces multiple diagnostic
        round-trips when debugging why a GN setup produces no output.

        Args:
            object_name: Name of the object to evaluate.
        """
        return _run(textwrap.dedent(f"""\
            import bpy, json
            obj = bpy.data.objects.get({object_name!r})
            if not obj:
                print(json.dumps({{"error": f"object {object_name!r} not found", "available": [o.name for o in bpy.data.objects]}}))
            else:
                dg = bpy.context.evaluated_depsgraph_get()
                eval_obj = obj.evaluated_get(dg)
                result = {{
                    "name": obj.name,
                    "type": obj.type,
                }}
                data = eval_obj.data
                if data and hasattr(data, 'vertices'):
                    result["mesh"] = {{"verts": len(data.vertices), "edges": len(data.edges), "faces": len(data.polygons)}}
                if data and hasattr(data, 'points'):
                    result["points"] = len(data.points)
                if data and hasattr(data, 'curves'):
                    result["curves"] = len(data.curves)
                _inst = sum(1 for _i in dg.object_instances if _i.is_instance and _i.parent and _i.parent.original == obj)
                result["instances"] = _inst
                if data and hasattr(data, 'attributes'):
                    _attrs = {{}}
                    for _a in data.attributes:
                        _attrs.setdefault(_a.domain, []).append(_a.name)
                    result["attributes"] = _attrs
                # Modifier info
                mods = []
                for mod in obj.modifiers:
                    mod_info = {{"name": mod.name, "type": mod.type}}
                    if hasattr(mod, 'node_group'):
                        mod_info["node_group"] = mod.node_group.name if mod.node_group else None
                    if hasattr(mod, 'node_warnings'):
                        mod_info["warnings"] = [str(w) for w in mod.node_warnings]
                    mods.append(mod_info)
                result["modifiers"] = mods
                result["modifier_count"] = len(mods)
                print(json.dumps(result))
        """))
