"""Tests for Stage 5 — Layer 1 gaps + Layer 4 pipeline tools."""

import json
import pytest
from unittest.mock import MagicMock


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
def pipeline_tools():
    """Register pipeline tools with mock MCP + transport, return (tools_dict, transport)."""
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
    type(mock_transport).dirty = property(lambda self: self._dirty)
    mock_transport.mark_dirty = lambda: setattr(mock_transport, '_dirty', True)
    mock_transport.clear_dirty = lambda: setattr(mock_transport, '_dirty', False)
    mock_transport.execute_python.return_value = {"output": "ok"}

    from synthgen.mcp.tools.pipeline import register
    register(mock_mcp, lambda: mock_transport)
    return registered, mock_transport


# === 5.1: Layer 1 tools =====================================================


class TestConfigureRender:
    def test_registered(self, registered_tools):
        fns, _ = registered_tools
        assert "configure_render" in fns

    def test_sets_engine(self, registered_tools):
        fns, transport = registered_tools
        fns["configure_render"](engine="CYCLES")
        code = transport.execute_python.call_args[0][0]
        assert "scene.render.engine = 'CYCLES'" in code

    def test_sets_resolution(self, registered_tools):
        fns, transport = registered_tools
        fns["configure_render"](resolution_x=1920, resolution_y=1080)
        code = transport.execute_python.call_args[0][0]
        assert "scene.render.resolution_x = 1920" in code
        assert "scene.render.resolution_y = 1080" in code

    def test_sets_samples_cycles(self, registered_tools):
        fns, transport = registered_tools
        fns["configure_render"](samples=256)
        code = transport.execute_python.call_args[0][0]
        assert "scene.cycles.samples = 256" in code

    def test_sets_output_path(self, registered_tools):
        fns, transport = registered_tools
        fns["configure_render"](output_path="/tmp/render_")
        code = transport.execute_python.call_args[0][0]
        assert "scene.render.filepath = '/tmp/render_'" in code

    def test_sets_file_format(self, registered_tools):
        fns, transport = registered_tools
        fns["configure_render"](file_format="OPEN_EXR")
        code = transport.execute_python.call_args[0][0]
        assert "scene.render.image_settings.file_format = 'OPEN_EXR'" in code

    def test_sets_film_transparent(self, registered_tools):
        fns, transport = registered_tools
        fns["configure_render"](film_transparent=True)
        code = transport.execute_python.call_args[0][0]
        assert "scene.render.film_transparent = True" in code

    def test_omitted_params_not_in_code(self, registered_tools):
        fns, transport = registered_tools
        fns["configure_render"](engine="CYCLES")
        code = transport.execute_python.call_args[0][0]
        assert "resolution_x" not in code
        assert "filepath" not in code

    def test_marks_dirty(self, registered_tools):
        fns, transport = registered_tools
        fns["configure_render"](engine="CYCLES")
        transport.mark_dirty.assert_called_once()


class TestImportAsset:
    def test_registered(self, registered_tools):
        fns, _ = registered_tools
        assert "import_asset" in fns

    def test_auto_detect_fbx(self, registered_tools):
        fns, transport = registered_tools
        fns["import_asset"](filepath="/path/model.fbx")
        code = transport.execute_python.call_args[0][0]
        assert "import_scene.fbx" in code

    def test_auto_detect_obj(self, registered_tools):
        fns, transport = registered_tools
        fns["import_asset"](filepath="/path/model.obj")
        code = transport.execute_python.call_args[0][0]
        assert "wm.obj_import" in code

    def test_auto_detect_glb(self, registered_tools):
        fns, transport = registered_tools
        fns["import_asset"](filepath="/path/model.glb")
        code = transport.execute_python.call_args[0][0]
        assert "import_scene.gltf" in code

    def test_auto_detect_stl(self, registered_tools):
        fns, transport = registered_tools
        fns["import_asset"](filepath="/path/model.stl")
        code = transport.execute_python.call_args[0][0]
        assert "wm.stl_import" in code

    def test_blend_import(self, registered_tools):
        fns, transport = registered_tools
        fns["import_asset"](filepath="/path/file.blend")
        code = transport.execute_python.call_args[0][0]
        assert "bpy.data.libraries.load" in code
        assert "link=False" in code

    def test_blend_link(self, registered_tools):
        fns, transport = registered_tools
        fns["import_asset"](filepath="/path/file.blend", link=True)
        code = transport.execute_python.call_args[0][0]
        assert "link=True" in code

    def test_unsupported_format(self, registered_tools):
        fns, transport = registered_tools
        result = fns["import_asset"](filepath="/path/model.xyz")
        parsed = json.loads(result)
        assert "error" in parsed
        assert "BLEND" in parsed["available"]

    def test_explicit_format_override(self, registered_tools):
        fns, transport = registered_tools
        fns["import_asset"](filepath="/path/data.bin", file_format="FBX")
        code = transport.execute_python.call_args[0][0]
        assert "import_scene.fbx" in code

    def test_tracks_imported_objects(self, registered_tools):
        fns, transport = registered_tools
        fns["import_asset"](filepath="/path/model.fbx")
        code = transport.execute_python.call_args[0][0]
        assert "before = set(bpy.data.objects.keys())" in code
        assert "after = set(bpy.data.objects.keys())" in code


class TestEditMesh:
    def test_registered(self, registered_tools):
        fns, _ = registered_tools
        assert "edit_mesh" in fns

    def test_subdivide(self, registered_tools):
        fns, transport = registered_tools
        fns["edit_mesh"](object_name="Cube", operation="subdivide", params={"cuts": 3})
        code = transport.execute_python.call_args[0][0]
        assert "bpy.ops.mesh.subdivide(number_cuts=3)" in code
        assert "mode_set(mode='EDIT')" in code
        assert "mode_set(mode='OBJECT')" in code

    def test_bevel(self, registered_tools):
        fns, transport = registered_tools
        fns["edit_mesh"](object_name="Cube", operation="bevel", params={"width": 0.2, "segments": 3})
        code = transport.execute_python.call_args[0][0]
        assert "bpy.ops.mesh.bevel(width=0.2, segments=3)" in code

    def test_triangulate(self, registered_tools):
        fns, transport = registered_tools
        fns["edit_mesh"](object_name="Cube", operation="triangulate")
        code = transport.execute_python.call_args[0][0]
        assert "quads_convert_to_tris" in code

    def test_merge_by_distance(self, registered_tools):
        fns, transport = registered_tools
        fns["edit_mesh"](object_name="Cube", operation="merge_by_distance", params={"threshold": 0.01})
        code = transport.execute_python.call_args[0][0]
        assert "remove_doubles(threshold=0.01)" in code

    def test_unknown_operation(self, registered_tools):
        fns, transport = registered_tools
        result = fns["edit_mesh"](object_name="Cube", operation="invalid_op")
        parsed = json.loads(result)
        assert "error" in parsed
        assert "subdivide" in parsed["available"]

    def test_select_all_before_op(self, registered_tools):
        fns, transport = registered_tools
        fns["edit_mesh"](object_name="Cube", operation="subdivide")
        code = transport.execute_python.call_args[0][0]
        assert "select_all(action='SELECT')" in code

    def test_default_params(self, registered_tools):
        fns, transport = registered_tools
        fns["edit_mesh"](object_name="Cube", operation="subdivide")
        code = transport.execute_python.call_args[0][0]
        assert "number_cuts=1" in code


class TestAddKeyframes:
    def test_registered(self, registered_tools):
        fns, _ = registered_tools
        assert "add_keyframes" in fns

    def test_simple_keyframes(self, registered_tools):
        fns, transport = registered_tools
        fns["add_keyframes"](
            object_name="Cube",
            data_path="location",
            keyframes=[{"frame": 1, "value": [0, 0, 0]}, {"frame": 24, "value": [5, 0, 0]}],
        )
        code = transport.execute_python.call_args[0][0]
        assert "scene.frame_set(1)" in code
        assert "scene.frame_set(24)" in code
        assert "keyframe_insert" in code

    def test_dotted_path_uses_exec(self, registered_tools):
        fns, transport = registered_tools
        fns["add_keyframes"](
            object_name="Light",
            data_path="data.energy",
            keyframes=[{"frame": 1, "value": 100.0}],
        )
        code = transport.execute_python.call_args[0][0]
        assert "exec(" in code

    def test_simple_path_uses_setattr(self, registered_tools):
        fns, transport = registered_tools
        fns["add_keyframes"](
            object_name="Cube",
            data_path="location",
            keyframes=[{"frame": 1, "value": [0, 0, 0]}],
        )
        code = transport.execute_python.call_args[0][0]
        assert "setattr(" in code

    def test_index_parameter(self, registered_tools):
        fns, transport = registered_tools
        fns["add_keyframes"](
            object_name="Cube",
            data_path="location",
            keyframes=[{"frame": 1, "value": 5.0}],
            index=0,
        )
        code = transport.execute_python.call_args[0][0]
        assert "index=0" in code


# === 5.2: Layer 4 pipeline tools =============================================


class TestSetParameter:
    def test_registered(self, pipeline_tools):
        fns, _ = pipeline_tools
        assert "set_parameter" in fns

    def test_sets_modifier_socket(self, pipeline_tools):
        fns, transport = pipeline_tools
        fns["set_parameter"](
            object_name="Cube",
            modifier_name="GeometryNodes",
            socket_identifier="Socket_2",
            value=0.5,
        )
        code = transport.execute_python.call_args[0][0]
        assert "mod['Socket_2'] = 0.5" in code

    def test_validates_object(self, pipeline_tools):
        fns, transport = pipeline_tools
        fns["set_parameter"](
            object_name="Cube",
            modifier_name="GeometryNodes",
            socket_identifier="Socket_2",
            value=1.0,
        )
        code = transport.execute_python.call_args[0][0]
        assert "bpy.data.objects.get('Cube')" in code

    def test_validates_modifier(self, pipeline_tools):
        fns, transport = pipeline_tools
        fns["set_parameter"](
            object_name="Cube",
            modifier_name="MyMod",
            socket_identifier="Socket_1",
            value=True,
        )
        code = transport.execute_python.call_args[0][0]
        assert "obj.modifiers.get('MyMod')" in code

    def test_marks_dirty(self, pipeline_tools):
        fns, transport = pipeline_tools
        fns["set_parameter"](
            object_name="Cube",
            modifier_name="GN",
            socket_identifier="Socket_1",
            value=1.0,
        )
        assert transport._dirty is True

    def test_vector_value(self, pipeline_tools):
        fns, transport = pipeline_tools
        fns["set_parameter"](
            object_name="Cube",
            modifier_name="GN",
            socket_identifier="Socket_1",
            value=[1.0, 2.0, 3.0],
        )
        code = transport.execute_python.call_args[0][0]
        assert "[1.0, 2.0, 3.0]" in code


class TestRender:
    def test_registered(self, pipeline_tools):
        fns, _ = pipeline_tools
        assert "render" in fns

    def test_renders(self, pipeline_tools):
        fns, transport = pipeline_tools
        fns["render"]()
        code = transport.execute_python.call_args[0][0]
        assert "bpy.ops.render.render(write_still=True)" in code

    def test_sets_output_path(self, pipeline_tools):
        fns, transport = pipeline_tools
        fns["render"](output_path="/tmp/out.png")
        code = transport.execute_python.call_args[0][0]
        assert "scene.render.filepath = '/tmp/out.png'" in code

    def test_provenance_snapshot(self, pipeline_tools):
        fns, transport = pipeline_tools
        fns["render"](save_provenance=True)
        code = transport.execute_python.call_args[0][0]
        assert "LiveGraph" in code
        assert ".provenance.json" in code

    def test_no_provenance(self, pipeline_tools):
        fns, transport = pipeline_tools
        fns["render"](save_provenance=False)
        code = transport.execute_python.call_args[0][0]
        assert "LiveGraph" not in code
        assert ".provenance.json" not in code

    def test_resolves_dirty(self, pipeline_tools):
        fns, transport = pipeline_tools
        transport._dirty = True
        fns["render"]()
        code = transport.execute_python.call_args[0][0]
        assert "resolve_attr_bridges" in code
        assert transport._dirty is False

    def test_no_resolve_when_clean(self, pipeline_tools):
        fns, transport = pipeline_tools
        transport._dirty = False
        fns["render"]()
        code = transport.execute_python.call_args[0][0]
        assert "resolve_attr_bridges" not in code

    def test_does_not_mark_dirty(self, pipeline_tools):
        fns, transport = pipeline_tools
        transport._dirty = False
        fns["render"]()
        assert transport._dirty is False


class TestSweep:
    def test_registered(self, pipeline_tools):
        fns, _ = pipeline_tools
        assert "sweep" in fns

    def test_generates_sweep_code(self, pipeline_tools):
        fns, transport = pipeline_tools
        fns["sweep"](
            object_name="Cube",
            modifier_name="GN",
            parameters=[{"socket": "Socket_1", "values": [0.1, 0.5]}],
            output_dir="/tmp/sweep",
        )
        code = transport.execute_python.call_args[0][0]
        assert "itertools.product" in code
        assert "bpy.ops.render.render(write_still=True)" in code

    def test_cartesian_product(self, pipeline_tools):
        fns, transport = pipeline_tools
        fns["sweep"](
            object_name="Cube",
            modifier_name="GN",
            parameters=[
                {"socket": "Socket_1", "values": [0.1, 0.5]},
                {"socket": "Socket_2", "values": [1, 2]},
            ],
            output_dir="/tmp/sweep",
        )
        code = transport.execute_python.call_args[0][0]
        assert "['Socket_1', 'Socket_2']" in code
        assert "[[0.1, 0.5], [1, 2]]" in code

    def test_seeds(self, pipeline_tools):
        fns, transport = pipeline_tools
        fns["sweep"](
            object_name="Cube",
            modifier_name="GN",
            parameters=[{"socket": "Socket_1", "values": [1.0]}],
            output_dir="/tmp/sweep",
            seeds=[42, 99],
        )
        code = transport.execute_python.call_args[0][0]
        assert "scene.cycles.seed = seed" in code
        assert "[42, 99]" in code

    def test_file_format(self, pipeline_tools):
        fns, transport = pipeline_tools
        fns["sweep"](
            object_name="Cube",
            modifier_name="GN",
            parameters=[{"socket": "S", "values": [1]}],
            output_dir="/tmp/sweep",
            file_format="OPEN_EXR",
        )
        code = transport.execute_python.call_args[0][0]
        assert "'OPEN_EXR'" in code
        assert ".exr" in code

    def test_creates_output_dir(self, pipeline_tools):
        fns, transport = pipeline_tools
        fns["sweep"](
            object_name="Cube",
            modifier_name="GN",
            parameters=[{"socket": "S", "values": [1]}],
            output_dir="/tmp/sweep",
        )
        code = transport.execute_python.call_args[0][0]
        assert "os.makedirs(output_dir, exist_ok=True)" in code

    def test_provenance_per_sample(self, pipeline_tools):
        fns, transport = pipeline_tools
        fns["sweep"](
            object_name="Cube",
            modifier_name="GN",
            parameters=[{"socket": "S", "values": [1]}],
            output_dir="/tmp/sweep",
            save_provenance=True,
        )
        code = transport.execute_python.call_args[0][0]
        assert "LiveGraph" in code
        assert ".provenance.json" in code

    def test_no_provenance(self, pipeline_tools):
        fns, transport = pipeline_tools
        fns["sweep"](
            object_name="Cube",
            modifier_name="GN",
            parameters=[{"socket": "S", "values": [1]}],
            output_dir="/tmp/sweep",
            save_provenance=False,
        )
        code = transport.execute_python.call_args[0][0]
        assert "LiveGraph" not in code

    def test_resolves_dirty(self, pipeline_tools):
        fns, transport = pipeline_tools
        transport._dirty = True
        fns["sweep"](
            object_name="Cube",
            modifier_name="GN",
            parameters=[{"socket": "S", "values": [1]}],
            output_dir="/tmp/sweep",
        )
        code = transport.execute_python.call_args[0][0]
        assert "resolve_attr_bridges" in code
        assert transport._dirty is False

    def test_manifest_output(self, pipeline_tools):
        fns, transport = pipeline_tools
        fns["sweep"](
            object_name="Cube",
            modifier_name="GN",
            parameters=[{"socket": "S", "values": [1]}],
            output_dir="/tmp/sweep",
        )
        code = transport.execute_python.call_args[0][0]
        assert "manifest.append(sample)" in code
        assert '"count": len(manifest)' in code


class TestExportLabels:
    def test_registered(self, pipeline_tools):
        fns, _ = pipeline_tools
        assert "export_labels" in fns

    def test_inspects_compositor(self, pipeline_tools):
        fns, transport = pipeline_tools
        fns["export_labels"]()
        code = transport.execute_python.call_args[0][0]
        assert "scene.compositing_node_group" in code

    def test_finds_file_output_nodes(self, pipeline_tools):
        fns, transport = pipeline_tools
        fns["export_labels"]()
        code = transport.execute_python.call_args[0][0]
        assert "CompositorNodeOutputFile" in code

    def test_finds_render_layers(self, pipeline_tools):
        fns, transport = pipeline_tools
        fns["export_labels"]()
        code = transport.execute_python.call_args[0][0]
        assert "CompositorNodeRLayers" in code

    def test_checks_link_info(self, pipeline_tools):
        fns, transport = pipeline_tools
        fns["export_labels"]()
        code = transport.execute_python.call_args[0][0]
        assert "from_node" in code
        assert "from_socket" in code

    def test_does_not_mutate(self, pipeline_tools):
        fns, transport = pipeline_tools
        transport._dirty = False
        fns["export_labels"]()
        assert transport._dirty is False
