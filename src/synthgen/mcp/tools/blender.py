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

    def _run(code: str, mutates: bool = False) -> str:
        transport = get_transport()
        if mutates:
            transport.mark_dirty()
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
        return _run(code, mutates=True)

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
        """), mutates=True)

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
        """), mutates=True)

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
        """), mutates=True)

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
        return _run(code, mutates=True)

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
        """), mutates=True)

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
        """), mutates=True)

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
        """), mutates=True)

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
        """), mutates=True)

    # --- Layer 2b: Procedural Authoring (Stage 4) ----------------------------

    @mcp.tool()
    def expose_parameter(
        tree_name: str,
        socket_type: str,
        socket_name: str,
        default_value: str | float | list | None = None,
        min_value: float | None = None,
        max_value: float | None = None,
        in_out: str = "INPUT",
    ) -> str:
        """Add a socket to a Geometry Nodes group interface for external control.

        This exposes a parameter on the modifier panel so it can be driven,
        keyframed, or swept across a dataset. Prefer this over hard-coding
        values inside the node tree.

        Args:
            tree_name: Name of the GN node group.
            socket_type: Socket type — "NodeSocketFloat", "NodeSocketInt",
                        "NodeSocketVector", "NodeSocketColor", "NodeSocketBool",
                        "NodeSocketMaterial", "NodeSocketObject".
            socket_name: Display name for the socket.
            default_value: Optional default value.
            min_value: Optional minimum (float/int sockets only).
            max_value: Optional maximum (float/int sockets only).
            in_out: "INPUT" (default) or "OUTPUT".
        """
        lines = [
            "import bpy, json",
            f"tree = bpy.data.node_groups.get({tree_name!r})",
            "if not tree:",
            f'    print("ERROR: node group {tree_name!r} not found")',
            "else:",
            f"    sock = tree.interface.new_socket(name={socket_name!r}, in_out={in_out!r}, socket_type={socket_type!r})",
        ]
        if default_value is not None:
            lines.append(f"    sock.default_value = {default_value!r}")
        if min_value is not None:
            lines.append(f"    sock.min_value = {min_value!r}")
        if max_value is not None:
            lines.append(f"    sock.max_value = {max_value!r}")
        lines.append('    print(json.dumps({"name": sock.name, "type": sock.bl_socket_idname, "identifier": sock.identifier}))')
        return _run("\n".join(lines), mutates=True)

    _ID_COLLECTIONS = {
        "OBJECT": "objects", "SCENE": "scenes", "MATERIAL": "materials",
        "WORLD": "worlds", "MESH": "meshes", "CAMERA": "cameras",
        "LIGHT": "lights", "NODE_TREE": "node_groups",
    }

    @mcp.tool()
    def add_driver(
        target_object: str,
        target_path: str,
        expression: str,
        variables: list[dict] | None = None,
        target_index: int = -1,
    ) -> str:
        """Add a driver expression to an object property.

        Drivers compute property values from expressions, linking properties
        across objects without manual keyframing. Use for procedural variation
        that depends on other scene state.

        Args:
            target_object: Name of the object to receive the driver.
            target_path: RNA path of the driven property (e.g. "location[0]",
                        "modifiers[\"GeometryNodes\"][\"Socket_1\"]").
            expression: Driver expression (e.g. "var * 2", "frame / 24").
            variables: Optional list of variable definitions, each a dict with:
                      - name: variable name in the expression
                      - id_type: ID type ("OBJECT", "SCENE", "MATERIAL", etc.)
                      - id_name: name of the data-block
                      - data_path: RNA path to the property
            target_index: Array index (-1 for non-array properties).
        """
        var_lines = []
        if variables:
            for v in variables:
                vname = v.get("name", "var")
                id_type = v.get("id_type", "OBJECT")
                collection = _ID_COLLECTIONS.get(id_type, id_type.lower() + "s")
                var_lines.append(
                    f"    v = drv.driver.variables.new()\n"
                    f"    v.name = {vname!r}\n"
                    f"    v.targets[0].id_type = {id_type!r}\n"
                    f"    v.targets[0].id = bpy.data.{collection}.get({v.get('id_name', '')!r})\n"
                    f"    v.targets[0].data_path = {v.get('data_path', '')!r}"
                )

        code = textwrap.dedent(f"""\
            import bpy, json
            obj = bpy.data.objects.get({target_object!r})
            if not obj:
                print(f"ERROR: object {target_object!r} not found")
            else:
                drv = obj.driver_add({target_path!r}, {target_index})
                drv.driver.type = 'SCRIPTED'
                drv.driver.expression = {expression!r}
        """)
        if var_lines:
            code += "\n".join(var_lines) + "\n"
        code += f'    print(json.dumps({{"target": {target_object!r}, "path": {target_path!r}, "expression": {expression!r}}}))\n'
        return _run(code, mutates=True)

    @mcp.tool()
    def wire_attr_bridge(
        gn_tree_name: str,
        material_name: str,
        attr_name: str,
        data_type: str = "FLOAT",
        domain: str = "POINT",
        attribute_type: str = "INSTANCER",
        gn_writer_name: str | None = None,
        shader_reader_name: str | None = None,
    ) -> str:
        """Wire a GN-to-shader attribute bridge — the core synthetic-data channel.

        Creates a Store Named Attribute node in the GN tree (writer) and an
        Attribute node in the shader (reader), pre-configured so the three
        alignment rules are satisfied: name, data type, and domain/attribute_type.

        IMPORTANT: data_type is set BEFORE linking the Value socket (the active
        socket changes with data_type). See knowledge/attribute_bridge.md.

        Args:
            gn_tree_name: Name of the Geometry Nodes group.
            material_name: Name of the material with shader nodes.
            attr_name: Attribute name string (must match exactly).
            data_type: GN data type — "FLOAT", "INT", "FLOAT_VECTOR",
                      "FLOAT_COLOR", "BOOLEAN", etc.
            domain: GN storage domain — "POINT", "INSTANCE", "FACE", etc.
            attribute_type: Shader read mode — "INSTANCER" (while instanced),
                          "GEOMETRY" (after Realize Instances), "OBJECT".
            gn_writer_name: Optional custom name for the Store Named Attribute node.
            shader_reader_name: Optional custom name for the Attribute node.
        """
        bd = _blender_dir()
        v = validate_node_type("GeometryNodeStoreNamedAttribute", "gn", blender_dir=bd)
        if not v.valid:
            return json.dumps({"error": "grounding", "message": v.message})
        v = validate_node_type("ShaderNodeAttribute", "shader", blender_dir=bd)
        if not v.valid:
            return json.dumps({"error": "grounding", "message": v.message})

        output_map = {
            "FLOAT": "Fac",
            "INT": "Fac",
            "FLOAT_VECTOR": "Vector",
            "FLOAT_COLOR": "Color",
            "BOOLEAN": "Fac",
        }
        shader_output = output_map.get(data_type, "Fac")

        w_name = f"    writer.name = {gn_writer_name!r}" if gn_writer_name else ""
        r_name = f"    reader.name = {shader_reader_name!r}" if shader_reader_name else ""

        code = textwrap.dedent(f"""\
            import bpy, json
            tree = bpy.data.node_groups.get({gn_tree_name!r})
            mat = bpy.data.materials.get({material_name!r})
            if not tree:
                print(f"ERROR: GN tree {gn_tree_name!r} not found")
            elif not mat or not mat.use_nodes:
                print(f"ERROR: material {material_name!r} not found or has no shader nodes")
            else:
                # Writer: Store Named Attribute in GN
                writer = tree.nodes.new('GeometryNodeStoreNamedAttribute')
                writer.data_type = {data_type!r}
                writer.domain = {domain!r}
            {w_name}
                writer.inputs['Name'].default_value = {attr_name!r}

                # Reader: Attribute in shader
                stree = mat.node_tree
                reader = stree.nodes.new('ShaderNodeAttribute')
                reader.attribute_type = {attribute_type!r}
                reader.attribute_name = {attr_name!r}
            {r_name}

                print(json.dumps({{
                    "attr_name": {attr_name!r},
                    "writer": {{
                        "name": writer.name, "tree": {gn_tree_name!r},
                        "data_type": {data_type!r}, "domain": {domain!r},
                        "inputs": [s.identifier for s in writer.inputs],
                        "outputs": [s.identifier for s in writer.outputs],
                    }},
                    "reader": {{
                        "name": reader.name, "tree": mat.name,
                        "attribute_type": {attribute_type!r},
                        "shader_output": {shader_output!r},
                        "outputs": [s.identifier for s in reader.outputs],
                    }},
                }}))
        """)
        return _run(code, mutates=True)

    @mcp.tool()
    def wire_compositor_pass(
        pass_name: str,
        output_path: str,
        file_format: str = "PNG",
        layer_name: str = "ViewLayer",
    ) -> str:
        """Wire a render pass to a File Output node in the compositor.

        Creates a File Output node and links the specified render pass
        to it. Uses scene.compositing_node_group (Blender 5.x API).

        Args:
            pass_name: Render pass output to connect (e.g. "Image", "Alpha",
                      or any pass enabled on the view layer).
            output_path: Base path for the output files.
            file_format: File format — "PNG", "OPEN_EXR", "JPEG", etc.
            layer_name: View layer name (default "ViewLayer").
        """
        bd = _blender_dir()
        v = validate_node_type("CompositorNodeRLayers", "compositor", blender_dir=bd)
        if not v.valid:
            return json.dumps({"error": "grounding", "message": v.message})
        v = validate_node_type("CompositorNodeOutputFile", "compositor", blender_dir=bd)
        if not v.valid:
            return json.dumps({"error": "grounding", "message": v.message})

        code = textwrap.dedent(f"""\
            import bpy, json
            scene = bpy.context.scene
            scene.use_nodes = True
            tree = scene.compositing_node_group
            if tree is None:
                print("ERROR: compositor node group not found — enable compositing first")
            else:
                # Find or create Render Layers node
                rl = None
                for n in tree.nodes:
                    if n.bl_idname == 'CompositorNodeRLayers' and n.layer == {layer_name!r}:
                        rl = n
                        break
                if not rl:
                    rl = tree.nodes.new('CompositorNodeRLayers')
                    rl.layer = {layer_name!r}

                # Create File Output node
                fo = tree.nodes.new('CompositorNodeOutputFile')
                fo.base_path = {output_path!r}
                fo.format.file_format = {file_format!r}
                fo.name = f"File Output ({pass_name!r})"

                # Link the pass
                src_sock = rl.outputs.get({pass_name!r})
                if not src_sock:
                    avail = [s.identifier for s in rl.outputs]
                    print(json.dumps({{"error": f"pass {pass_name!r} not found", "available": avail}}))
                else:
                    tree.links.new(src_sock, fo.inputs[0])
                    print(json.dumps({{
                        "render_layers": rl.name,
                        "file_output": fo.name,
                        "pass": {pass_name!r},
                        "path": {output_path!r},
                        "format": {file_format!r},
                    }}))
        """)
        return _run(code, mutates=True)

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
        return _run(code, mutates=True)
