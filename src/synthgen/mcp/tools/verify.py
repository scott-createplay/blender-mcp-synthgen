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
        """Check whether a named attribute exists on an object's evaluated mesh.

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
