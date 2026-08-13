"""MCP tools for Blender scene mutation — setup + procedural authoring.

Layer 1 (setup) tools create components: objects, materials, etc.
Layer 2 (procedural) tools wire node graphs with grounded identifiers.
"""

from __future__ import annotations

import json
import textwrap
from typing import TYPE_CHECKING

from synthgen.mcp.grounding import validate_node_type, validate_socket, validate_setting

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP
    from synthgen.mcp.transport import TransportBackend


def register(mcp: FastMCP, get_transport, get_blender_dir=None) -> None:

    def _run(code: str) -> str:
        transport = get_transport()
        result = transport.execute_python(code)
        if isinstance(result, dict):
            return result.get("output", json.dumps(result))
        return str(result)

    def _blender_dir() -> str | None:
        return get_blender_dir() if get_blender_dir else None

    # --- Layer 1: Scene Setup -----------------------------------------------

    @mcp.tool()
    def create_object(
        name: str,
        type: str = "MESH",
        mesh_type: str = "cube",
        location: list[float] | None = None,
        scale: list[float] | None = None,
    ) -> str:
        """Create a new object in the scene. Use this for building components
        that feed into procedural systems. For variation across a dataset,
        use procedural tools (add_gn_modifier, add_node, link_sockets) instead.

        Args:
            name: Name for the new object.
            type: Object type — "MESH", "EMPTY", "CURVE", "LIGHT", "CAMERA".
            mesh_type: For MESH type — "cube", "sphere", "cylinder", "plane", "cone", "torus".
            location: [x, y, z] world position. Defaults to origin.
            scale: [x, y, z] scale. Defaults to [1, 1, 1].
        """
        loc = location or [0, 0, 0]
        sc = scale or [1, 1, 1]
        mesh_ops = {
            "cube": "bpy.ops.mesh.primitive_cube_add",
            "sphere": "bpy.ops.mesh.primitive_uv_sphere_add",
            "cylinder": "bpy.ops.mesh.primitive_cylinder_add",
            "plane": "bpy.ops.mesh.primitive_plane_add",
            "cone": "bpy.ops.mesh.primitive_cone_add",
            "torus": "bpy.ops.mesh.primitive_torus_add",
        }
        if type == "MESH":
            op = mesh_ops.get(mesh_type, "bpy.ops.mesh.primitive_cube_add")
            code = textwrap.dedent(f"""\
                import bpy
                {op}(location={loc})
                obj = bpy.context.active_object
                obj.name = {name!r}
                obj.scale = {sc}
                print(f"Created MESH object '{{obj.name}}'")
            """)
        elif type == "EMPTY":
            code = textwrap.dedent(f"""\
                import bpy
                bpy.ops.object.empty_add(type='PLAIN_AXES', location={loc})
                obj = bpy.context.active_object
                obj.name = {name!r}
                obj.scale = {sc}
                print(f"Created EMPTY '{{obj.name}}'")
            """)
        elif type == "CAMERA":
            code = textwrap.dedent(f"""\
                import bpy
                cam_data = bpy.data.cameras.new({name!r})
                obj = bpy.data.objects.new({name!r}, cam_data)
                bpy.context.collection.objects.link(obj)
                obj.location = {loc}
                print(f"Created CAMERA '{{obj.name}}'")
            """)
        elif type == "LIGHT":
            code = textwrap.dedent(f"""\
                import bpy
                light_data = bpy.data.lights.new({name!r}, type='POINT')
                obj = bpy.data.objects.new({name!r}, light_data)
                bpy.context.collection.objects.link(obj)
                obj.location = {loc}
                print(f"Created LIGHT '{{obj.name}}'")
            """)
        else:
            return f"Unsupported object type: {type}"
        return _run(code)

    @mcp.tool()
    def create_material(name: str, base_color: list[float] | None = None) -> str:
        """Create a new material with shader nodes enabled.

        Args:
            name: Material name.
            base_color: Optional [R, G, B, A] base color (0-1 range).
        """
        color = base_color or [0.8, 0.8, 0.8, 1.0]
        return _run(textwrap.dedent(f"""\
            import bpy
            mat = bpy.data.materials.new({name!r})
            mat.use_nodes = True
            bsdf = mat.node_tree.nodes.get("Principled BSDF")
            if bsdf:
                bsdf.inputs["Base Color"].default_value = {color}
            print(f"Created material '{{mat.name}}'")
        """))

    @mcp.tool()
    def assign_material(object_name: str, material_name: str) -> str:
        """Assign a material to an object.

        Args:
            object_name: Name of the target object.
            material_name: Name of the material to assign.
        """
        return _run(textwrap.dedent(f"""\
            import bpy
            obj = bpy.data.objects.get({object_name!r})
            mat = bpy.data.materials.get({material_name!r})
            if not obj:
                print(f"ERROR: object {object_name!r} not found")
            elif not mat:
                print(f"ERROR: material {material_name!r} not found")
            else:
                if obj.data and hasattr(obj.data, 'materials'):
                    obj.data.materials.append(mat)
                print(f"Assigned '{{mat.name}}' to '{{obj.name}}'")
        """))

    @mcp.tool()
    def set_parent(child_name: str, parent_name: str) -> str:
        """Set the parent of an object.

        Args:
            child_name: Name of the child object.
            parent_name: Name of the parent object.
        """
        return _run(textwrap.dedent(f"""\
            import bpy
            child = bpy.data.objects.get({child_name!r})
            parent = bpy.data.objects.get({parent_name!r})
            if not child:
                print(f"ERROR: child {child_name!r} not found")
            elif not parent:
                print(f"ERROR: parent {parent_name!r} not found")
            else:
                child.parent = parent
                print(f"Parented '{{child.name}}' to '{{parent.name}}'")
        """))

    # --- Layer 2: Procedural Authoring --------------------------------------

    @mcp.tool()
    def add_gn_modifier(object_name: str, modifier_name: str = "GeometryNodes", tree_name: str | None = None) -> str:
        """Add a Geometry Nodes modifier to an object.

        Creates a new node group if tree_name is not specified, or assigns
        an existing one.

        Args:
            object_name: Target object name.
            modifier_name: Name for the modifier.
            tree_name: Optional existing node group name to assign.
        """
        if tree_name:
            code = textwrap.dedent(f"""\
                import bpy
                obj = bpy.data.objects.get({object_name!r})
                if not obj:
                    print(f"ERROR: object {object_name!r} not found")
                else:
                    mod = obj.modifiers.new({modifier_name!r}, 'NODES')
                    tree = bpy.data.node_groups.get({tree_name!r})
                    if tree:
                        mod.node_group = tree
                    print(f"Added GN modifier '{{mod.name}}' with tree '{{mod.node_group.name if mod.node_group else 'NEW'}}'")
            """)
        else:
            code = textwrap.dedent(f"""\
                import bpy
                obj = bpy.data.objects.get({object_name!r})
                if not obj:
                    print(f"ERROR: object {object_name!r} not found")
                else:
                    mod = obj.modifiers.new({modifier_name!r}, 'NODES')
                    print(f"Added GN modifier '{{mod.name}}' with tree '{{mod.node_group.name if mod.node_group else 'NEW'}}'")
            """)
        return _run(code)

    @mcp.tool()
    def add_node(tree_name: str, node_type: str, name: str | None = None, tree_context: str = "gn") -> str:
        """Add a node to a node tree by grounded type ID.

        Use schema_find or schema_show first to get the correct node_type.
        The node_type must be a real Blender node identifier — this tool
        does not accept display labels.

        Args:
            tree_name: Name of the node tree (node group, material, or compositor group).
            node_type: Blender node type ID (e.g. "GeometryNodeDistributePointsOnFaces").
            name: Optional custom name for the node.
            tree_context: Where to find the tree — "gn" (bpy.data.node_groups),
                         "shader" (material.node_tree), "compositor" (scene.compositing_node_group).
        """
        v = validate_node_type(node_type, tree_context, blender_dir=_blender_dir())
        if not v.valid:
            return json.dumps({"error": "grounding", "message": v.message, "suggestions": v.suggestions})

        if tree_context == "shader":
            tree_lookup = f"bpy.data.materials.get({tree_name!r}).node_tree"
        elif tree_context == "compositor":
            tree_lookup = "bpy.context.scene.compositing_node_group"
        else:
            tree_lookup = f"bpy.data.node_groups.get({tree_name!r})"

        name_line = f"node.name = {name!r}" if name else ""
        return _run(textwrap.dedent(f"""\
            import bpy, json
            tree = {tree_lookup}
            if not tree:
                print("ERROR: tree not found")
            else:
                node = tree.nodes.new({node_type!r})
                {name_line}
                print(json.dumps({{
                    "name": node.name,
                    "type": node.bl_idname,
                    "inputs": [s.identifier for s in node.inputs],
                    "outputs": [s.identifier for s in node.outputs],
                }}))
        """))

    @mcp.tool()
    def link_sockets(
        tree_name: str,
        from_node: str,
        from_socket: str,
        to_node: str,
        to_socket: str,
        tree_context: str = "gn",
    ) -> str:
        """Connect two sockets in a node tree.

        Use socket IDENTIFIERS (from schema_show), not display labels.

        Args:
            tree_name: Node tree name.
            from_node: Name of the output node.
            from_socket: Output socket identifier.
            to_node: Name of the input node.
            to_socket: Input socket identifier.
            tree_context: "gn", "shader", or "compositor".
        """
        if tree_context == "shader":
            tree_lookup = f"bpy.data.materials.get({tree_name!r}).node_tree"
        elif tree_context == "compositor":
            tree_lookup = "bpy.context.scene.compositing_node_group"
        else:
            tree_lookup = f"bpy.data.node_groups.get({tree_name!r})"

        return _run(textwrap.dedent(f"""\
            import bpy
            tree = {tree_lookup}
            if not tree:
                print("ERROR: tree not found")
            else:
                src_node = tree.nodes.get({from_node!r})
                dst_node = tree.nodes.get({to_node!r})
                if not src_node:
                    print(f"ERROR: node {from_node!r} not found. Available: {{[n.name for n in tree.nodes]}}")
                elif not dst_node:
                    print(f"ERROR: node {to_node!r} not found. Available: {{[n.name for n in tree.nodes]}}")
                else:
                    src_sock = src_node.outputs.get({from_socket!r})
                    dst_sock = dst_node.inputs.get({to_socket!r})
                    if not src_sock:
                        print(f"ERROR: output socket {from_socket!r} not found on {{src_node.name}}. Available: {{[s.identifier for s in src_node.outputs]}}")
                    elif not dst_sock:
                        print(f"ERROR: input socket {to_socket!r} not found on {{dst_node.name}}. Available: {{[s.identifier for s in dst_node.inputs]}}")
                    else:
                        tree.links.new(src_sock, dst_sock)
                        print(f"Linked {{src_node.name}}.{{src_sock.identifier}} -> {{dst_node.name}}.{{dst_sock.identifier}}")
        """))

    @mcp.tool()
    def set_node_property(
        tree_name: str,
        node_name: str,
        property_name: str,
        value: str,
        tree_context: str = "gn",
        node_type: str | None = None,
    ) -> str:
        """Set a property on a node (e.g. data_type, domain, operation).

        Args:
            tree_name: Node tree name.
            node_name: Name of the node.
            property_name: Property to set (e.g. "data_type", "domain", "operation").
            value: Value to set (as string — enums are strings in bpy).
            tree_context: "gn", "shader", or "compositor".
            node_type: Optional node type ID for static validation against schema.
        """
        if node_type:
            v = validate_setting(node_type, property_name, tree_context, blender_dir=_blender_dir())
            if not v.valid:
                return json.dumps({"error": "grounding", "message": v.message, "suggestions": v.suggestions})
        if tree_context == "shader":
            tree_lookup = f"bpy.data.materials.get({tree_name!r}).node_tree"
        elif tree_context == "compositor":
            tree_lookup = "bpy.context.scene.compositing_node_group"
        else:
            tree_lookup = f"bpy.data.node_groups.get({tree_name!r})"

        return _run(textwrap.dedent(f"""\
            import bpy
            tree = {tree_lookup}
            node = tree.nodes.get({node_name!r}) if tree else None
            if not node:
                print(f"ERROR: node {node_name!r} not found")
            else:
                setattr(node, {property_name!r}, {value!r})
                print(f"Set {{node.name}}.{property_name} = {value!r}")
        """))

    @mcp.tool()
    def set_socket_default(
        tree_name: str,
        node_name: str,
        socket_name: str,
        value: str | float | list,
        is_input: bool = True,
        tree_context: str = "gn",
        node_type: str | None = None,
    ) -> str:
        """Set the default value of a socket on a node.

        Args:
            tree_name: Node tree name.
            node_name: Name of the node.
            socket_name: Socket identifier (not label — use schema_show to check).
            value: Value to set. Floats, strings, or lists (for vectors/colors).
            is_input: True for input sockets (default), False for outputs.
            tree_context: "gn", "shader", or "compositor".
            node_type: Optional node type ID for static validation against schema.
        """
        if node_type:
            v = validate_socket(node_type, socket_name, tree_context, is_input=is_input, blender_dir=_blender_dir())
            if not v.valid:
                return json.dumps({"error": "grounding", "message": v.message, "suggestions": v.suggestions})
        if tree_context == "shader":
            tree_lookup = f"bpy.data.materials.get({tree_name!r}).node_tree"
        elif tree_context == "compositor":
            tree_lookup = "bpy.context.scene.compositing_node_group"
        else:
            tree_lookup = f"bpy.data.node_groups.get({tree_name!r})"

        io = "inputs" if is_input else "outputs"
        return _run(textwrap.dedent(f"""\
            import bpy
            tree = {tree_lookup}
            node = tree.nodes.get({node_name!r}) if tree else None
            if not node:
                print(f"ERROR: node {node_name!r} not found")
            else:
                sock = node.{io}.get({socket_name!r})
                if not sock:
                    print(f"ERROR: socket {socket_name!r} not found. Available: {{[s.identifier for s in node.{io}]}}")
                else:
                    sock.default_value = {value!r}
                    print(f"Set {{node.name}}.{socket_name} = {value!r}")
        """))

    @mcp.tool()
    def execute_python(code: str, reason: str = "") -> str:
        """Execute arbitrary Python code in Blender. ESCAPE HATCH — use structured
        tools (create_object, add_node, link_sockets) when possible.

        This operation is tagged as UNGROUNDED. The scene graph may change in ways
        the introspection layer can't track. A full re-resolve will be triggered
        on the next graph query.

        Args:
            code: Python code to execute (bpy is available in scope).
            reason: Why structured tools can't handle this. Required for audit trail.
        """
        return _run(code)
