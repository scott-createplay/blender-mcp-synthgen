"""Tests for Stage 4 — procedural authoring tools + dirty-flag invalidation."""

import json
import pytest
from unittest.mock import MagicMock, call


@pytest.fixture()
def registered_tools():
    """Register blender tools with mock MCP + transport, return (tools_dict, transport)."""
    mock_mcp = MagicMock()
    registered = {}

    def capture_tool():
        def decorator(fn):
            registered[fn.__name__] = fn
            return fn
        return decorator

    mock_mcp.tool = capture_tool
    mock_transport = MagicMock()
    mock_transport.execute_python.return_value = {"output": "ok"}
    mock_transport.dirty = False

    from synthgen.mcp.tools.blender import register
    register(mock_mcp, lambda: mock_transport, get_blender_dir=lambda: None)
    return registered, mock_transport


@pytest.fixture()
def graph_tools():
    """Register graph tools with mock MCP + transport, return (tools_dict, transport)."""
    mock_mcp = MagicMock()
    registered = {}

    def capture_tool():
        def decorator(fn):
            registered[fn.__name__] = fn
            return fn
        return decorator

    mock_mcp.tool = capture_tool

    mock_transport = MagicMock()
    mock_transport._dirty = False
    type(mock_transport).dirty = property(
        lambda self: self._dirty,
    )
    mock_transport.mark_dirty = lambda: setattr(mock_transport, '_dirty', True)
    mock_transport.clear_dirty = lambda: setattr(mock_transport, '_dirty', False)
    mock_transport.execute_python.return_value = {"output": "[]"}

    from synthgen.mcp.tools.graph import register
    register(mock_mcp, lambda: mock_transport)
    return registered, mock_transport


# --- 4.1: expose_parameter ---------------------------------------------------

class TestExposeParameter:
    def test_registered(self, registered_tools):
        fns, _ = registered_tools
        assert "expose_parameter" in fns

    def test_generates_interface_new_socket(self, registered_tools):
        fns, transport = registered_tools
        fns["expose_parameter"](
            tree_name="MyGN",
            socket_type="NodeSocketFloat",
            socket_name="Scale",
        )
        transport.execute_python.assert_called_once()
        code = transport.execute_python.call_args[0][0]
        assert "tree.interface.new_socket" in code
        assert "'Scale'" in code
        assert "'NodeSocketFloat'" in code
        assert "'INPUT'" in code

    def test_default_value(self, registered_tools):
        fns, transport = registered_tools
        fns["expose_parameter"](
            tree_name="MyGN",
            socket_type="NodeSocketFloat",
            socket_name="Scale",
            default_value=1.5,
        )
        code = transport.execute_python.call_args[0][0]
        assert "sock.default_value = 1.5" in code

    def test_min_max(self, registered_tools):
        fns, transport = registered_tools
        fns["expose_parameter"](
            tree_name="MyGN",
            socket_type="NodeSocketFloat",
            socket_name="Scale",
            min_value=0.0,
            max_value=10.0,
        )
        code = transport.execute_python.call_args[0][0]
        assert "sock.min_value = 0.0" in code
        assert "sock.max_value = 10.0" in code

    def test_output_socket(self, registered_tools):
        fns, transport = registered_tools
        fns["expose_parameter"](
            tree_name="MyGN",
            socket_type="NodeSocketFloat",
            socket_name="Result",
            in_out="OUTPUT",
        )
        code = transport.execute_python.call_args[0][0]
        assert "'OUTPUT'" in code

    def test_marks_dirty(self, registered_tools):
        fns, transport = registered_tools
        fns["expose_parameter"](
            tree_name="MyGN",
            socket_type="NodeSocketFloat",
            socket_name="Scale",
        )
        transport.mark_dirty.assert_called()


# --- 4.2: add_driver --------------------------------------------------------

class TestAddDriver:
    def test_registered(self, registered_tools):
        fns, _ = registered_tools
        assert "add_driver" in fns

    def test_simple_expression(self, registered_tools):
        fns, transport = registered_tools
        fns["add_driver"](
            target_object="Cube",
            target_path="location[0]",
            expression="frame / 24",
        )
        transport.execute_python.assert_called_once()
        code = transport.execute_python.call_args[0][0]
        assert "obj.driver_add('location[0]'" in code
        assert "drv.driver.expression = 'frame / 24'" in code
        assert "drv.driver.type = 'SCRIPTED'" in code

    def test_with_variables(self, registered_tools):
        fns, transport = registered_tools
        fns["add_driver"](
            target_object="Cube",
            target_path="location[0]",
            expression="var * 2",
            variables=[{
                "name": "var",
                "id_type": "OBJECT",
                "id_name": "Empty",
                "data_path": "location[0]",
            }],
        )
        code = transport.execute_python.call_args[0][0]
        assert "drv.driver.variables.new()" in code
        assert "v.name = 'var'" in code
        assert "v.targets[0].id_type = 'OBJECT'" in code
        assert "bpy.data.objects.get('Empty')" in code
        assert "v.targets[0].data_path = 'location[0]'" in code

    def test_material_variable(self, registered_tools):
        fns, transport = registered_tools
        fns["add_driver"](
            target_object="Cube",
            target_path="location[0]",
            expression="var",
            variables=[{
                "name": "var",
                "id_type": "MATERIAL",
                "id_name": "MyMat",
                "data_path": "node_tree.nodes[0].inputs[0].default_value",
            }],
        )
        code = transport.execute_python.call_args[0][0]
        assert "bpy.data.materials.get('MyMat')" in code

    def test_print_inside_else_block(self, registered_tools):
        """The success print must be indented inside the else: block."""
        fns, transport = registered_tools
        fns["add_driver"](
            target_object="Cube",
            target_path="location[0]",
            expression="frame",
        )
        code = transport.execute_python.call_args[0][0]
        lines = code.split("\n")
        print_lines = [l for l in lines if "json.dumps" in l]
        assert len(print_lines) == 1
        assert print_lines[0].startswith("    ")

    def test_marks_dirty(self, registered_tools):
        fns, transport = registered_tools
        fns["add_driver"](
            target_object="Cube",
            target_path="location[0]",
            expression="frame",
        )
        transport.mark_dirty.assert_called()


# --- 4.3: wire_attr_bridge ---------------------------------------------------

class TestWireAttrBridge:
    def test_registered(self, registered_tools):
        fns, _ = registered_tools
        assert "wire_attr_bridge" in fns

    def test_creates_writer_and_reader(self, registered_tools):
        fns, transport = registered_tools
        fns["wire_attr_bridge"](
            gn_tree_name="MyGN",
            material_name="MyMat",
            attr_name="rust",
        )
        transport.execute_python.assert_called_once()
        code = transport.execute_python.call_args[0][0]
        assert "GeometryNodeStoreNamedAttribute" in code
        assert "ShaderNodeAttribute" in code

    def test_data_type_set_before_value_link(self, registered_tools):
        """data_type must be set BEFORE the Value socket is accessible."""
        fns, transport = registered_tools
        fns["wire_attr_bridge"](
            gn_tree_name="MyGN",
            material_name="MyMat",
            attr_name="rust",
            data_type="FLOAT_COLOR",
        )
        code = transport.execute_python.call_args[0][0]
        dt_pos = code.index("writer.data_type")
        name_pos = code.index("writer.inputs['Name']")
        assert dt_pos < name_pos

    def test_attribute_name_is_property_not_socket(self, registered_tools):
        """ShaderNodeAttribute name is set via node.attribute_name, not an input socket."""
        fns, transport = registered_tools
        fns["wire_attr_bridge"](
            gn_tree_name="MyGN",
            material_name="MyMat",
            attr_name="color_var",
        )
        code = transport.execute_python.call_args[0][0]
        assert "reader.attribute_name = 'color_var'" in code

    def test_attribute_type_default_instancer(self, registered_tools):
        fns, transport = registered_tools
        fns["wire_attr_bridge"](
            gn_tree_name="MyGN",
            material_name="MyMat",
            attr_name="rust",
        )
        code = transport.execute_python.call_args[0][0]
        assert "reader.attribute_type = 'INSTANCER'" in code

    def test_attribute_type_geometry(self, registered_tools):
        fns, transport = registered_tools
        fns["wire_attr_bridge"](
            gn_tree_name="MyGN",
            material_name="MyMat",
            attr_name="rust",
            attribute_type="GEOMETRY",
        )
        code = transport.execute_python.call_args[0][0]
        assert "reader.attribute_type = 'GEOMETRY'" in code

    def test_output_map_float(self, registered_tools):
        fns, transport = registered_tools
        fns["wire_attr_bridge"](
            gn_tree_name="MyGN",
            material_name="MyMat",
            attr_name="rust",
            data_type="FLOAT",
        )
        code = transport.execute_python.call_args[0][0]
        assert '"shader_output": \'Fac\'' in code

    def test_output_map_color(self, registered_tools):
        fns, transport = registered_tools
        fns["wire_attr_bridge"](
            gn_tree_name="MyGN",
            material_name="MyMat",
            attr_name="inst_col",
            data_type="FLOAT_COLOR",
        )
        code = transport.execute_python.call_args[0][0]
        assert '"shader_output": \'Color\'' in code

    def test_output_map_vector(self, registered_tools):
        fns, transport = registered_tools
        fns["wire_attr_bridge"](
            gn_tree_name="MyGN",
            material_name="MyMat",
            attr_name="dir",
            data_type="FLOAT_VECTOR",
        )
        code = transport.execute_python.call_args[0][0]
        assert '"shader_output": \'Vector\'' in code

    def test_custom_node_names(self, registered_tools):
        fns, transport = registered_tools
        fns["wire_attr_bridge"](
            gn_tree_name="MyGN",
            material_name="MyMat",
            attr_name="rust",
            gn_writer_name="RustWriter",
            shader_reader_name="RustReader",
        )
        code = transport.execute_python.call_args[0][0]
        assert "writer.name = 'RustWriter'" in code
        assert "reader.name = 'RustReader'" in code

    def test_grounding_validates_both_nodes(self, registered_tools):
        """Both Store Named Attribute and Attribute nodes must pass grounding."""
        fns, _ = registered_tools
        result = fns["wire_attr_bridge"](
            gn_tree_name="MyGN",
            material_name="MyMat",
            attr_name="rust",
        )
        assert "error" not in result or result == "ok"

    def test_marks_dirty(self, registered_tools):
        fns, transport = registered_tools
        fns["wire_attr_bridge"](
            gn_tree_name="MyGN",
            material_name="MyMat",
            attr_name="rust",
        )
        transport.mark_dirty.assert_called()


# --- 4.4: wire_compositor_pass -----------------------------------------------

class TestWireCompositorPass:
    def test_registered(self, registered_tools):
        fns, _ = registered_tools
        assert "wire_compositor_pass" in fns

    def test_creates_render_layers_and_file_output(self, registered_tools):
        fns, transport = registered_tools
        fns["wire_compositor_pass"](
            pass_name="Image",
            output_path="/tmp/renders/",
        )
        transport.execute_python.assert_called_once()
        code = transport.execute_python.call_args[0][0]
        assert "CompositorNodeRLayers" in code
        assert "CompositorNodeOutputFile" in code

    def test_uses_compositing_node_group(self, registered_tools):
        """Must use scene.compositing_node_group (Blender 5.x API)."""
        fns, transport = registered_tools
        fns["wire_compositor_pass"](
            pass_name="Image",
            output_path="/tmp/renders/",
        )
        code = transport.execute_python.call_args[0][0]
        assert "scene.compositing_node_group" in code
        assert "scene.node_tree" not in code

    def test_file_format(self, registered_tools):
        fns, transport = registered_tools
        fns["wire_compositor_pass"](
            pass_name="Image",
            output_path="/tmp/renders/",
            file_format="OPEN_EXR",
        )
        code = transport.execute_python.call_args[0][0]
        assert "'OPEN_EXR'" in code

    def test_custom_layer(self, registered_tools):
        fns, transport = registered_tools
        fns["wire_compositor_pass"](
            pass_name="Image",
            output_path="/tmp/renders/",
            layer_name="CustomLayer",
        )
        code = transport.execute_python.call_args[0][0]
        assert "'CustomLayer'" in code

    def test_grounding_validates_compositor_nodes(self, registered_tools):
        fns, _ = registered_tools
        result = fns["wire_compositor_pass"](
            pass_name="Image",
            output_path="/tmp/renders/",
        )
        assert "error" not in result or result == "ok"

    def test_marks_dirty(self, registered_tools):
        fns, transport = registered_tools
        fns["wire_compositor_pass"](
            pass_name="Image",
            output_path="/tmp/renders/",
        )
        transport.mark_dirty.assert_called()


# --- 4.5: dirty-flag invalidation -------------------------------------------

class TestDirtyFlag:
    def test_mutating_tool_marks_dirty(self, registered_tools):
        fns, transport = registered_tools
        fns["add_node"]("MyTree", "GeometryNodeDistributePointsOnFaces", tree_context="gn")
        transport.mark_dirty.assert_called()

    def test_graph_tool_resolves_when_dirty(self, graph_tools):
        fns, transport = graph_tools
        transport._dirty = True
        fns["graph_nodes"]()
        code = transport.execute_python.call_args[0][0]
        assert "resolve_attr_bridges" in code
        assert not transport._dirty

    def test_graph_tool_skips_resolve_when_clean(self, graph_tools):
        fns, transport = graph_tools
        transport._dirty = False
        fns["graph_nodes"]()
        code = transport.execute_python.call_args[0][0]
        assert "resolve_attr_bridges" not in code

    def test_attribute_trace_always_resolves(self, graph_tools):
        fns, transport = graph_tools
        transport._dirty = False
        fns["graph_attribute_trace"]("rust")
        code = transport.execute_python.call_args[0][0]
        assert "resolve_attr_bridges" in code

    def test_graph_preamble_clears_dirty(self, graph_tools):
        fns, transport = graph_tools
        transport._dirty = True
        fns["graph_neighbors"]("OBJ:Cube")
        assert not transport._dirty


# --- Tool count check -------------------------------------------------------

class TestToolCount:
    def test_all_stage4_tools_registered(self, registered_tools):
        fns, _ = registered_tools
        stage4_tools = [
            "expose_parameter",
            "add_driver",
            "wire_attr_bridge",
            "wire_compositor_pass",
        ]
        for name in stage4_tools:
            assert name in fns, f"{name} not registered"

    def test_total_tool_count(self, registered_tools):
        fns, _ = registered_tools
        assert len(fns) >= 14
