"""Tests for Stage 1 — mutation hardening (timeout, error handling, safety guards).

This file accumulates tests across the Stage 1 sub-steps. Start with 1.1
(transport timeout with actionable error message); later steps append here.
"""

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


# --- 1.1: transport timeout with actionable error message -------------------

class TestTransportTimeout:
    def test_timeout_error_propagates_from_mutation_tool(self, registered_tools):
        """A RuntimeError raised by transport.execute_python (e.g. on timeout)
        must propagate out of a mutation tool call, not be swallowed."""
        fns, transport = registered_tools
        transport.execute_python.side_effect = RuntimeError(
            "Blender did not respond within 30s — the main thread may be "
            "blocked; the session likely needs a restart."
        )
        with pytest.raises(RuntimeError):
            fns["create_object"](name="Cube", type="MESH", mesh_type="cube")

    def test_timeout_message_includes_seconds_and_restart_guidance(self, registered_tools):
        """The timeout error message must be actionable: it should mention the
        timeout duration and advise that the session needs a restart."""
        fns, transport = registered_tools
        timeout_seconds = 30
        transport.execute_python.side_effect = RuntimeError(
            f"Blender did not respond within {timeout_seconds}s — the main thread "
            "may be blocked; the session likely needs a restart."
        )
        with pytest.raises(RuntimeError) as exc_info:
            fns["create_object"](name="Cube", type="MESH", mesh_type="cube")
        message = str(exc_info.value)
        assert f"{timeout_seconds}s" in message
        assert "restart" in message.lower()

    def test_executor_execute_python_raises_runtime_error_on_timeout(self):
        """AddonTransport.execute_python must convert a concurrent.futures
        TimeoutError into a RuntimeError with an actionable message, using a
        default timeout shorter than the old 180s."""
        import sys
        import types

        # addon/synthgen_mcp/executor.py guards `import bpy`, so it's importable
        # without Blender. Import it directly from the addon package path.
        addon_src = None
        import os
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        executor_path = os.path.join(repo_root, "addon", "synthgen_mcp", "executor.py")
        assert os.path.exists(executor_path), executor_path

        spec_name = "synthgen_mcp_executor_under_test"
        import importlib.util
        spec = importlib.util.spec_from_file_location(spec_name, executor_path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec_name] = module
        spec.loader.exec_module(module)

        executor = module.MainThreadExecutor()
        transport = module.AddonTransport(executor)

        # Don't start the executor's timer loop — the submitted future will
        # never be resolved, so execute_python must time out quickly.
        with pytest.raises(RuntimeError) as exc_info:
            transport.execute_python("1 + 1", timeout=0.1)

        message = str(exc_info.value)
        assert "0.1s" in message
        assert "restart" in message.lower()

        del sys.modules[spec_name]

    def test_executor_default_timeout_is_30_seconds(self):
        """Default timeout should be 30s (down from the old 180s) so a hung
        main thread fails fast with an actionable message."""
        import inspect
        import os
        import importlib.util
        import sys

        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        executor_path = os.path.join(repo_root, "addon", "synthgen_mcp", "executor.py")
        spec_name = "synthgen_mcp_executor_under_test_2"
        spec = importlib.util.spec_from_file_location(spec_name, executor_path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec_name] = module
        spec.loader.exec_module(module)

        sig = inspect.signature(module.AddonTransport.execute_python)
        assert sig.parameters["timeout"].default == 30

        del sys.modules[spec_name]


# --- 1.3: set_parameter — Blender 5.x GN modifier input API -----------------

@pytest.fixture()
def pipeline_tools():
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


class TestSetParameter5x:
    def test_generated_code_has_no_version_branching(self, pipeline_tools):
        """Version routing happens at code-gen time, not runtime."""
        fns, transport = pipeline_tools
        fns["set_parameter"](
            object_name="Cube",
            modifier_name="GeometryNodes",
            socket_identifier="Socket_2",
            value=1.5,
        )
        code = transport.execute_python.call_args[0][0]
        assert "bpy.app.version" not in code

    def test_5x_uses_bracket_access_on_properties_inputs(self, pipeline_tools):
        """Default version is 5.x — must use bracket access, not getattr."""
        fns, transport = pipeline_tools
        fns["set_parameter"](
            object_name="Cube",
            modifier_name="GeometryNodes",
            socket_identifier="Socket_2",
            value=1.5,
        )
        code = transport.execute_python.call_args[0][0]
        assert "mod.properties.inputs['Socket_2']['value'] = 1.5" in code
        assert "getattr" not in code

    def test_5x_error_on_missing_socket(self, pipeline_tools):
        fns, transport = pipeline_tools
        fns["set_parameter"](
            object_name="Cube",
            modifier_name="GeometryNodes",
            socket_identifier="Socket_2",
            value=1.5,
        )
        code = transport.execute_python.call_args[0][0]
        assert "ERROR" in code


# --- 1.4: expose_parameter — validate before mutate, coerce int -------------

class TestExposeParameterRollback:
    def test_int_socket_default_value_coerced(self, registered_tools):
        fns, transport = registered_tools
        fns["expose_parameter"](
            tree_name="Geometry Nodes",
            socket_type="NodeSocketInt",
            socket_name="Count",
            default_value=3.7,
        )
        code = transport.execute_python.call_args_list[0][0][0]
        assert "int(" in code

    def test_float_socket_default_value_not_coerced_with_int(self, registered_tools):
        fns, transport = registered_tools
        fns["expose_parameter"](
            tree_name="Geometry Nodes",
            socket_type="NodeSocketFloat",
            socket_name="Radius",
            default_value=1.5,
        )
        code = transport.execute_python.call_args_list[0][0][0]
        # No int() coercion should be applied for a non-int socket type.
        assert "sock.default_value = int(" not in code

    def test_try_except_rollback_present_when_assignments_given(self, registered_tools):
        fns, transport = registered_tools
        fns["expose_parameter"](
            tree_name="Geometry Nodes",
            socket_type="NodeSocketInt",
            socket_name="Count",
            default_value=3,
            min_value=0,
            max_value=10,
        )
        code = transport.execute_python.call_args_list[0][0][0]
        assert "try:" in code
        assert "except Exception" in code
        assert "tree.interface.remove(sock)" in code
        assert "rolled_back" in code

    def test_no_try_except_when_no_assignments(self, registered_tools):
        fns, transport = registered_tools
        fns["expose_parameter"](
            tree_name="Geometry Nodes",
            socket_type="NodeSocketFloat",
            socket_name="Radius",
        )
        code = transport.execute_python.call_args_list[0][0][0]
        assert "try:" not in code
        assert "tree.interface.remove(sock)" not in code


# --- 1.5: execute_python — reason is required --------------------------------

class TestExecutePythonReasonRequired:
    def test_reason_has_no_default(self, registered_tools):
        import inspect
        fns, _ = registered_tools
        sig = inspect.signature(fns["execute_python"])
        assert sig.parameters["reason"].default is inspect.Parameter.empty

    def test_calling_without_reason_raises_type_error(self, registered_tools):
        fns, _ = registered_tools
        with pytest.raises(TypeError):
            fns["execute_python"](code="1 + 1")


# --- create_node_group / remove_object / remove_collection -------------------

class TestCreateNodeGroup:
    def test_default_geometry_node_tree(self, registered_tools):
        fns, transport = registered_tools
        fns["create_node_group"](name="MyGroup")
        code = transport.execute_python.call_args_list[0][0][0]
        assert "bpy.data.node_groups.new" in code
        assert "GeometryNodeTree" in code
        assert "MyGroup" in code

    def test_shader_node_tree_type(self, registered_tools):
        fns, transport = registered_tools
        fns["create_node_group"](name="MyShaderGroup", tree_type="ShaderNodeTree")
        code = transport.execute_python.call_args_list[0][0][0]
        assert "bpy.data.node_groups.new" in code
        assert "ShaderNodeTree" in code

    def test_mutates_true(self, registered_tools):
        fns, transport = registered_tools
        fns["create_node_group"](name="MyGroup")
        transport.mark_dirty.assert_called_once()


class TestRemoveObject:
    def test_generated_code_removes_object(self, registered_tools):
        fns, transport = registered_tools
        fns["remove_object"](object_name="Cube")
        code = transport.execute_python.call_args_list[0][0][0]
        assert "bpy.data.objects.remove" in code
        assert "Cube" in code

    def test_generated_code_error_path_lists_available_objects(self, registered_tools):
        fns, transport = registered_tools
        fns["remove_object"](object_name="Nonexistent")
        code = transport.execute_python.call_args_list[0][0][0]
        assert "ERROR" in code
        assert "Available" in code

    def test_generated_code_unlinks_from_collections(self, registered_tools):
        fns, transport = registered_tools
        fns["remove_object"](object_name="Cube")
        code = transport.execute_python.call_args_list[0][0][0]
        assert "col.objects.unlink" in code
        assert "bpy.context.scene.collection.objects.unlink" in code

    def test_mutates_true(self, registered_tools):
        fns, transport = registered_tools
        fns["remove_object"](object_name="Cube")
        transport.mark_dirty.assert_called_once()


class TestRemoveCollection:
    def test_generated_code_removes_collection(self, registered_tools):
        fns, transport = registered_tools
        fns["remove_collection"](collection_name="MyCollection")
        code = transport.execute_python.call_args_list[0][0][0]
        assert "bpy.data.collections.remove" in code
        assert "MyCollection" in code

    def test_generated_code_error_path_lists_available_collections(self, registered_tools):
        fns, transport = registered_tools
        fns["remove_collection"](collection_name="Nonexistent")
        code = transport.execute_python.call_args_list[0][0][0]
        assert "ERROR" in code
        assert "Available" in code

    def test_remove_children_true_generates_child_removal_code(self, registered_tools):
        fns, transport = registered_tools
        fns["remove_collection"](collection_name="MyCollection", remove_children=True)
        code = transport.execute_python.call_args_list[0][0][0]
        assert "bpy.data.objects.remove" in code

    def test_remove_children_false_by_default(self, registered_tools):
        fns, transport = registered_tools
        fns["remove_collection"](collection_name="MyCollection")
        code = transport.execute_python.call_args_list[0][0][0]
        assert "bpy.data.collections.remove" in code

    def test_mutates_true(self, registered_tools):
        fns, transport = registered_tools
        fns["remove_collection"](collection_name="MyCollection")
        transport.mark_dirty.assert_called_once()


# --- remove_parameter --------------------------------------------------------

class TestRemoveParameter:
    def test_registered(self, registered_tools):
        fns, _ = registered_tools
        assert "remove_parameter" in fns

    def test_generates_interface_remove(self, registered_tools):
        fns, transport = registered_tools
        fns["remove_parameter"](tree_name="Geometry Nodes", socket_identifier="Socket_4")
        code = transport.execute_python.call_args_list[0][0][0]
        assert "tree.interface.remove" in code

    def test_returns_full_interface(self, registered_tools):
        fns, transport = registered_tools
        fns["remove_parameter"](tree_name="Geometry Nodes", socket_identifier="Socket_4")
        code = transport.execute_python.call_args_list[0][0][0]
        assert "items_tree" in code

    def test_mutates_true(self, registered_tools):
        fns, transport = registered_tools
        fns["remove_parameter"](tree_name="Geometry Nodes", socket_identifier="Socket_4")
        transport.mark_dirty.assert_called_once()


# --- get_modifier_inputs -----------------------------------------------------

@pytest.fixture()
def verify_tools():
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
    from synthgen.mcp.tools.verify import register
    register(mock_mcp, lambda: mock_transport)
    return registered, mock_transport


class TestGetModifierInputs:
    def test_registered(self, verify_tools):
        fns, _ = verify_tools
        assert "get_modifier_inputs" in fns

    def test_no_version_branching_in_generated_code(self, verify_tools):
        """Version routing happens at code-gen time, not runtime."""
        fns, transport = verify_tools
        fns["get_modifier_inputs"](object_name="Cube", modifier_name="GeometryNodes")
        code = transport.execute_python.call_args[0][0]
        assert "bpy.app.version" not in code

    def test_5x_uses_bracket_access(self, verify_tools):
        """Default version is 5.x — must use bracket access on properties.inputs."""
        fns, transport = verify_tools
        fns["get_modifier_inputs"](object_name="Cube", modifier_name="GeometryNodes")
        code = transport.execute_python.call_args[0][0]
        assert "properties.inputs[" in code
        assert "getattr" not in code
        assert "dir(" not in code

    def test_5x_surfaces_attribute_name(self, verify_tools):
        """5.x code should read attribute_name from the property."""
        fns, transport = verify_tools
        fns["get_modifier_inputs"](object_name="Cube", modifier_name="GeometryNodes")
        code = transport.execute_python.call_args[0][0]
        assert "attribute_name" in code

    def test_is_read_only(self, verify_tools):
        fns, transport = verify_tools
        fns["get_modifier_inputs"](object_name="Cube", modifier_name="GeometryNodes")
        transport.mark_dirty.assert_not_called()


# --- 4.1: evaluate_object ----------------------------------------------------

class TestEvaluateObject:
    def test_registered(self, verify_tools):
        fns, _ = verify_tools
        assert "evaluate_object" in fns

    def test_generated_code_uses_evaluated_depsgraph(self, verify_tools):
        fns, transport = verify_tools
        fns["evaluate_object"](object_name="Cube")
        code = transport.execute_python.call_args[0][0]
        assert "evaluated_depsgraph_get" in code

    def test_generated_code_checks_modifier_warnings(self, verify_tools):
        fns, transport = verify_tools
        fns["evaluate_object"](object_name="Cube")
        code = transport.execute_python.call_args[0][0]
        assert "node_warnings" in code

    def test_is_read_only(self, verify_tools):
        fns, transport = verify_tools
        fns["evaluate_object"](object_name="Cube")
        transport.mark_dirty.assert_not_called()


# --- 4.2: graph tools surface unresolved modifier state ----------------------

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
    type(mock_transport).dirty = property(lambda self: self._dirty)
    mock_transport.mark_dirty = lambda: setattr(mock_transport, '_dirty', True)
    mock_transport.clear_dirty = lambda: setattr(mock_transport, '_dirty', False)
    mock_transport.execute_python.return_value = {"output": "[]"}

    from synthgen.mcp.tools.graph import register
    register(mock_mcp, lambda: mock_transport)
    return registered, mock_transport


class TestGraphUnresolvedState:
    def test_graph_nodes_checks_for_unresolved_modifiers(self, graph_tools):
        fns, transport = graph_tools
        fns["graph_nodes"]()
        code = transport.execute_python.call_args[0][0]
        assert "node_group is None" in code

    def test_graph_neighbors_checks_for_unresolved_modifiers(self, graph_tools):
        fns, transport = graph_tools
        fns["graph_neighbors"](node_id="OBJ:Cube/MOD:GeometryNodes")
        code = transport.execute_python.call_args[0][0]
        assert "node_group is None" in code


# --- 4.3: auto-save sidecar after mutations ----------------------------------

class TestAutoSave:
    def test_individual_mutation_does_not_trigger_autosave(self, registered_tools):
        """Individual mutation tools no longer auto-save on every call — only
        compound tools (build_graph, wire_attr_bridge, wire_compositor_pass)
        and the explicit save_checkpoint tool do."""
        fns, transport = registered_tools
        fns["create_object"](name="Cube", type="MESH", mesh_type="cube")
        assert transport.execute_python.call_count == 1

    def test_compound_tool_triggers_autosave(self, registered_tools):
        fns, transport = registered_tools
        fns["build_graph"](
            tree_name="test",
            nodes=[{"type": "GeometryNodeMeshGrid", "name": "grid"}],
        )
        assert transport.execute_python.call_count == 2

    def test_autosave_code_uses_save_as_mainfile_with_copy(self, registered_tools):
        fns, transport = registered_tools
        fns["build_graph"](
            tree_name="test",
            nodes=[{"type": "GeometryNodeMeshGrid", "name": "grid"}],
        )
        save_code = transport.execute_python.call_args_list[1][0][0]
        assert "bpy.ops.wm.save_as_mainfile" in save_code
        assert "copy=True" in save_code

    def test_autosave_failure_does_not_break_tool_result(self, registered_tools):
        fns, transport = registered_tools
        transport.execute_python.side_effect = [
            {"output": '{"tree_name": "test"}'},
            RuntimeError("save failed"),
        ]
        result = fns["build_graph"](
            tree_name="test",
            nodes=[{"type": "GeometryNodeMeshGrid", "name": "grid"}],
        )
        assert "tree_name" in result

    def test_read_only_tool_does_not_trigger_autosave(self, verify_tools):
        fns, transport = verify_tools
        fns["get_modifier_inputs"](object_name="Cube", modifier_name="GeometryNodes")
        assert transport.execute_python.call_count == 1


# --- Stage 3.1: expose_parameter returns full interface ---------------------

class TestExposeParameterFullInterface:
    def test_full_interface_dumped_with_assignments(self, registered_tools):
        fns, transport = registered_tools
        fns["expose_parameter"](
            tree_name="Geometry Nodes",
            socket_type="NodeSocketFloat",
            socket_name="Radius",
            default_value=1.0,
        )
        code = transport.execute_python.call_args_list[0][0][0]
        assert "items_tree" in code
        assert '"interface":' in code

    def test_full_interface_dumped_without_assignments(self, registered_tools):
        fns, transport = registered_tools
        fns["expose_parameter"](
            tree_name="Geometry Nodes",
            socket_type="NodeSocketFloat",
            socket_name="Radius",
        )
        code = transport.execute_python.call_args_list[0][0][0]
        assert "items_tree" in code
        assert '"interface":' in code


# --- Stage 3.2: add_gn_modifier always creates + assigns tree ---------------

class TestAddGnModifierCreatesTree:
    def test_generated_code_creates_new_tree_when_no_tree_name(self, registered_tools):
        fns, transport = registered_tools
        fns["add_gn_modifier"](object_name="Cube")
        code = transport.execute_python.call_args_list[0][0][0]
        assert "bpy.data.node_groups.new" in code
        assert "NodeGroupInput" in code
        assert "NodeGroupOutput" in code
        assert '"tree_name"' in code

    def test_generated_code_includes_tree_name_with_existing_tree(self, registered_tools):
        fns, transport = registered_tools
        fns["add_gn_modifier"](object_name="Cube", tree_name="ExistingTree")
        code = transport.execute_python.call_args_list[0][0][0]
        assert '"tree_name"' in code


# --- Stage 3.3: expose_parameter refreshes bound modifiers ------------------

class TestExposeParameterRefreshesModifiers:
    def test_refresh_loop_present(self, registered_tools):
        fns, transport = registered_tools
        fns["expose_parameter"](
            tree_name="Geometry Nodes",
            socket_type="NodeSocketFloat",
            socket_name="Radius",
        )
        code = transport.execute_python.call_args_list[0][0][0]
        assert "bpy.data.objects" in code
        assert "_obj.modifiers" in code
        assert "show_viewport" in code
        assert '"refreshed_modifiers"' in code

    def test_refresh_loop_present_with_assignments(self, registered_tools):
        fns, transport = registered_tools
        fns["expose_parameter"](
            tree_name="Geometry Nodes",
            socket_type="NodeSocketFloat",
            socket_name="Radius",
            default_value=1.0,
        )
        code = transport.execute_python.call_args_list[0][0][0]
        assert "bpy.data.objects" in code
        assert "_obj.modifiers" in code
        assert "show_viewport" in code
        assert '"refreshed_modifiers"' in code


# --- Stage 3.4: ungrounded cost note appended to mutation results -----------

class TestUngroundedCostInMutations:
    def test_mutation_result_mentions_graph_cache_reresolve(self, registered_tools):
        fns, _ = registered_tools
        result = fns["create_object"](name="Cube", type="MESH", mesh_type="cube")
        assert "re-resolve" in result or "graph cache" in result


# --- Stage 5.1: build_graph compound tool ------------------------------------

class TestBuildGraph:
    def test_registered(self, registered_tools):
        fns, _ = registered_tools
        assert "build_graph" in fns

    def test_validates_all_nodes_before_mutation(self, registered_tools):
        """All node types must be validated before any code is sent to Blender."""
        fns, transport = registered_tools
        # Use an invalid node type — should fail with grounding error, no execute_python call
        result = fns["build_graph"](
            tree_name="test_tree",
            nodes=[{"type": "FakeNode123"}],
        )
        assert "grounding" in result
        transport.execute_python.assert_not_called()

    def test_single_script_for_full_graph(self, registered_tools):
        """A full graph spec should produce exactly one execute_python call
        (plus one auto-save call), not N calls."""
        fns, transport = registered_tools
        fns["build_graph"](
            tree_name="test",
            nodes=[
                {"type": "GeometryNodeDistributePointsOnFaces", "name": "scatter"},
                {"type": "GeometryNodeInputMeshFaceArea", "name": "area"},
            ],
            links=[
                {"from_node": "area", "from_socket": "Area",
                 "to_node": "scatter", "to_socket": "Density Factor"},
            ],
            parameters=[
                {"socket_type": "NodeSocketFloat", "name": "Density", "default": 10.0},
            ],
            defaults=[
                {"node": "scatter", "socket": "Distance Min", "value": 2.0},
            ],
        )
        # Should be exactly 2 calls: one for the graph build, one for auto-save
        assert transport.execute_python.call_count == 2

    def test_generated_code_creates_all_nodes(self, registered_tools):
        fns, transport = registered_tools
        fns["build_graph"](
            tree_name="test",
            nodes=[
                {"type": "GeometryNodeDistributePointsOnFaces", "name": "scatter"},
                {"type": "GeometryNodeInputMeshFaceArea", "name": "area"},
            ],
        )
        code = transport.execute_python.call_args_list[0][0][0]
        assert "GeometryNodeDistributePointsOnFaces" in code
        assert "GeometryNodeInputMeshFaceArea" in code
        assert "node_map" in code or "nodes" in code

    def test_generated_code_has_rollback(self, registered_tools):
        fns, transport = registered_tools
        fns["build_graph"](
            tree_name="test",
            nodes=[{"type": "GeometryNodeMeshGrid", "name": "grid"}],
        )
        code = transport.execute_python.call_args_list[0][0][0]
        assert "node_groups.remove" in code
        assert "rolled_back" in code

    def test_int_coercion_for_parameters(self, registered_tools):
        fns, transport = registered_tools
        fns["build_graph"](
            tree_name="test",
            nodes=[{"type": "GeometryNodeMeshGrid", "name": "grid"}],
            parameters=[
                {"socket_type": "NodeSocketInt", "name": "Seed", "default": 42.0},
            ],
        )
        code = transport.execute_python.call_args_list[0][0][0]
        assert "int(" in code

    def test_grounding_error_reports_all_failures(self, registered_tools):
        """If multiple nodes fail validation, all failures should be reported."""
        fns, transport = registered_tools
        result = fns["build_graph"](
            tree_name="test",
            nodes=[
                {"type": "FakeNode1"},
                {"type": "GeometryNodeMeshGrid"},  # valid
                {"type": "FakeNode2"},
            ],
        )
        parsed = json.loads(result)
        assert parsed["error"] == "grounding"
        assert len(parsed["failures"]) == 2
        transport.execute_python.assert_not_called()


# --- sweep() — Blender 5.x GN modifier input API -----------------------------

class TestSweep5x:
    def test_sweep_no_version_branching(self, pipeline_tools):
        """sweep() generated code should NOT branch on bpy.app.version — routing is at code-gen time."""
        fns, transport = pipeline_tools
        fns["sweep"](
            object_name="obj",
            modifier_name="mod",
            parameters=[{"socket": "Socket_1", "values": [1.0, 2.0]}],
            output_dir="/tmp/out",
        )
        code = transport.execute_python.call_args[0][0]
        assert "bpy.app.version" not in code

    def test_sweep_5x_uses_bracket_access(self, pipeline_tools):
        """Default version is 5.x — sweep must use bracket access."""
        fns, transport = pipeline_tools
        fns["sweep"](
            object_name="obj",
            modifier_name="mod",
            parameters=[{"socket": "Socket_1", "values": [1.0, 2.0]}],
            output_dir="/tmp/out",
        )
        code = transport.execute_python.call_args[0][0]
        assert "mod.properties.inputs[" in code
        assert "getattr" not in code


# --- save_checkpoint ----------------------------------------------------------

class TestSaveCheckpoint:
    def test_registered(self, registered_tools):
        fns, _ = registered_tools
        assert "save_checkpoint" in fns

    def test_calls_execute_python_with_save_code(self, registered_tools):
        fns, transport = registered_tools
        fns["save_checkpoint"]()
        transport.execute_python.assert_called_once()
        code = transport.execute_python.call_args[0][0]
        assert "bpy.ops.wm.save_as_mainfile" in code
        assert "copy=True" in code

    def test_returns_saved_true(self, registered_tools):
        fns, _ = registered_tools
        result = fns["save_checkpoint"]()
        parsed = json.loads(result)
        assert parsed["saved"] is True

    def test_does_not_mark_dirty(self, registered_tools):
        fns, transport = registered_tools
        fns["save_checkpoint"]()
        transport.mark_dirty.assert_not_called()

    def test_failure_is_swallowed(self, registered_tools):
        fns, transport = registered_tools
        transport.execute_python.side_effect = RuntimeError("save failed")
        result = fns["save_checkpoint"]()
        parsed = json.loads(result)
        assert parsed["saved"] is True


# --- list_tree_nodes -----------------------------------------------------------

class TestListTreeNodes:
    def test_registered(self, verify_tools):
        fns, _ = verify_tools
        assert "list_tree_nodes" in fns

    def test_generated_code_iterates_nodes(self, verify_tools):
        fns, transport = verify_tools
        fns["list_tree_nodes"](tree_name="MyTree")
        code = transport.execute_python.call_args[0][0]
        assert "tree.nodes" in code

    def test_is_read_only(self, verify_tools):
        fns, transport = verify_tools
        fns["list_tree_nodes"](tree_name="MyTree")
        transport.mark_dirty.assert_not_called()

    def test_shader_context(self, verify_tools):
        fns, transport = verify_tools
        fns["list_tree_nodes"](tree_name="MyMat", tree_context="shader")
        code = transport.execute_python.call_args[0][0]
        assert "bpy.data.materials.get" in code

    def test_compositor_context(self, verify_tools):
        fns, transport = verify_tools
        fns["list_tree_nodes"](tree_name="Comp", tree_context="compositor")
        code = transport.execute_python.call_args[0][0]
        assert "compositing_node_group" in code


# --- add_node duplicate-name safety --------------------------------------------

class TestAddNodeDuplicateCheck:
    def test_generated_code_checks_for_existing_node_when_name_given(self, registered_tools):
        fns, transport = registered_tools
        fns["add_node"]("MyTree", "GeometryNodeDistributePointsOnFaces", name="scatter", tree_context="gn")
        code = transport.execute_python.call_args_list[0][0][0]
        assert "tree.nodes.get('scatter')" in code
        assert "already exists" in code

    def test_no_duplicate_check_without_name(self, registered_tools):
        fns, transport = registered_tools
        fns["add_node"]("MyTree", "GeometryNodeDistributePointsOnFaces", tree_context="gn")
        code = transport.execute_python.call_args_list[0][0][0]
        assert "already exists" not in code


# --- build_graph duplicate node names -------------------------------------------

class TestBuildGraphDuplicateKeys:
    def test_duplicate_names_returns_error_without_execute(self, registered_tools):
        fns, transport = registered_tools
        result = fns["build_graph"](
            tree_name="test",
            nodes=[
                {"type": "GeometryNodeMeshGrid", "name": "dup"},
                {"type": "GeometryNodeMeshGrid", "name": "dup"},
            ],
        )
        parsed = json.loads(result)
        assert "duplicate" in parsed["error"]
        transport.execute_python.assert_not_called()


# --- /health version fields ---------------------------------------------------

class TestHealthVersionFields:
    """get_status() should include tools_hash, addon_version, blender_version."""

    @pytest.fixture(autouse=True)
    def _load_server(self):
        """Import server.py directly via importlib, bypassing __init__ (needs bpy)."""
        import importlib.util, types
        spec = importlib.util.spec_from_file_location(
            "synthgen_mcp_server",
            "addon/synthgen_mcp/server.py",
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self.server = mod

    def test_get_status_includes_version_fields(self):
        status = self.server.get_status()
        assert "tools_hash" in status
        assert "addon_version" in status
        assert "blender_version" in status

    def test_tools_hash_changes_with_tool_count(self):
        import hashlib
        old_hash = self.server._tools_hash

        self.server._tools_hash = hashlib.sha256(b"a|b|c").hexdigest()[:12]
        status = self.server.get_status()
        assert status["tools_hash"] == self.server._tools_hash
        self.server._tools_hash = old_hash

    def test_addon_version_format(self):
        self.server._addon_version = "0.2.0"
        status = self.server.get_status()
        assert status["addon_version"] == "0.2.0"
        self.server._addon_version = None


# --- auto-layout --------------------------------------------------------------

class TestAutoLayout:
    """Auto-layout code is injected into build_graph, add_node, link_sockets."""

    def test_layout_tool_registered(self, registered_tools):
        fns, _ = registered_tools
        assert "layout_node_tree" in fns

    def test_build_graph_includes_layout(self, registered_tools):
        fns, transport = registered_tools
        fns["build_graph"](
            tree_name="test",
            nodes=[
                {"type": "GeometryNodeMeshGrid", "name": "grid"},
                {"type": "GeometryNodeInputMeshFaceArea", "name": "area"},
            ],
        )
        code = transport.execute_python.call_args_list[0][0][0]
        assert "_al_nodes" in code
        assert "_al_layer" in code
        assert ".location" in code

    def test_add_node_includes_layout(self, registered_tools):
        fns, transport = registered_tools
        fns["add_node"]("MyTree", "GeometryNodeMeshGrid", tree_context="gn")
        code = transport.execute_python.call_args_list[0][0][0]
        assert "_al_nodes" in code

    def test_link_sockets_includes_layout(self, registered_tools):
        fns, transport = registered_tools
        fns["link_sockets"]("MyTree", "A", "out", "B", "in", tree_context="gn")
        code = transport.execute_python.call_args_list[0][0][0]
        assert "_al_nodes" in code

    def test_layout_standalone_generates_valid_code(self, registered_tools):
        fns, transport = registered_tools
        fns["layout_node_tree"]("MyTree", tree_context="gn")
        code = transport.execute_python.call_args_list[0][0][0]
        assert "_al_nodes" in code
        assert "laid_out" in code
