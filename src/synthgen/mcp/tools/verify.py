"""MCP tools for verification — confirm attributes, properties, and state."""

from __future__ import annotations

import json
import textwrap
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


def register(mcp: FastMCP, get_transport) -> None:

    def _run(code: str) -> str:
        transport = get_transport()
        result = transport.execute_python(code)
        if isinstance(result, dict):
            return result.get("output", json.dumps(result))
        return str(result)

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
        return _run(textwrap.dedent(f"""\
            import bpy, json
            obj = bpy.data.objects.get({object_name!r})
            if not obj:
                print(f"ERROR: object {object_name!r} not found. Available: {{[o.name for o in bpy.data.objects]}}")
            else:
                mod = obj.modifiers.get({modifier_name!r})
                if not mod:
                    print(f"ERROR: modifier {modifier_name!r} not found on {{obj.name}}. Available: {{[m.name for m in obj.modifiers]}}")
                else:
                    ver = bpy.app.version
                    inputs = []
                    if ver >= (5, 0, 0):
                        # 5.x: use mod.properties.inputs
                        for name in dir(mod.properties.inputs):
                            if name.startswith('_'):
                                continue
                            inp = getattr(mod.properties.inputs, name, None)
                            if inp is not None and hasattr(inp, 'default_value'):
                                inputs.append({{
                                    "identifier": name,
                                    "name": getattr(inp, 'name', name),
                                    "type": type(inp).__name__,
                                    "value": inp.default_value if not hasattr(inp.default_value, '__len__') else list(inp.default_value),
                                }})
                    else:
                        # 4.x: id-properties on the modifier
                        if mod.node_group:
                            for item in mod.node_group.interface.items_tree:
                                if hasattr(item, 'identifier') and item.in_out == 'INPUT':
                                    ident = item.identifier
                                    try:
                                        val = mod[ident]
                                        inputs.append({{"identifier": ident, "name": item.name, "type": item.bl_socket_idname, "value": val}})
                                    except (KeyError, TypeError):
                                        inputs.append({{"identifier": ident, "name": item.name, "type": item.bl_socket_idname, "value": None}})
                    print(json.dumps({{"object": {object_name!r}, "modifier": {modifier_name!r}, "inputs": inputs}}))
        """))
