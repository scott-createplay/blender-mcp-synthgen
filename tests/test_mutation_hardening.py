"""Tests for Stage 1 — mutation hardening (timeout, error handling, safety guards).

This file accumulates tests across the Stage 1 sub-steps. Start with 1.1
(transport timeout with actionable error message); later steps append here.
"""

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
    def test_generated_code_branches_on_blender_version(self, pipeline_tools):
        fns, transport = pipeline_tools
        fns["set_parameter"](
            object_name="Cube",
            modifier_name="GeometryNodes",
            socket_identifier="Socket_2",
            value=1.5,
        )
        code = transport.execute_python.call_args[0][0]
        assert "bpy.app.version" in code

    def test_generated_code_uses_properties_inputs_for_5x(self, pipeline_tools):
        fns, transport = pipeline_tools
        fns["set_parameter"](
            object_name="Cube",
            modifier_name="GeometryNodes",
            socket_identifier="Socket_2",
            value=1.5,
        )
        code = transport.execute_python.call_args[0][0]
        assert "mod.properties.inputs" in code

    def test_generated_code_keeps_4x_fallback(self, pipeline_tools):
        fns, transport = pipeline_tools
        fns["set_parameter"](
            object_name="Cube",
            modifier_name="GeometryNodes",
            socket_identifier="Socket_2",
            value=1.5,
        )
        code = transport.execute_python.call_args[0][0]
        assert "mod[" in code

    def test_generated_code_error_mentions_version_and_api_path(self, pipeline_tools):
        fns, transport = pipeline_tools
        fns["set_parameter"](
            object_name="Cube",
            modifier_name="GeometryNodes",
            socket_identifier="Socket_2",
            value=1.5,
        )
        code = transport.execute_python.call_args[0][0]
        assert "ERROR" in code
        assert "ver[0]" in code and "ver[1]" in code


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
        code = transport.execute_python.call_args[0][0]
        assert "int(" in code

    def test_float_socket_default_value_not_coerced_with_int(self, registered_tools):
        fns, transport = registered_tools
        fns["expose_parameter"](
            tree_name="Geometry Nodes",
            socket_type="NodeSocketFloat",
            socket_name="Radius",
            default_value=1.5,
        )
        code = transport.execute_python.call_args[0][0]
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
        code = transport.execute_python.call_args[0][0]
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
        code = transport.execute_python.call_args[0][0]
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
        code = transport.execute_python.call_args[0][0]
        assert "bpy.data.node_groups.new" in code
        assert "GeometryNodeTree" in code
        assert "MyGroup" in code

    def test_shader_node_tree_type(self, registered_tools):
        fns, transport = registered_tools
        fns["create_node_group"](name="MyShaderGroup", tree_type="ShaderNodeTree")
        code = transport.execute_python.call_args[0][0]
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
        code = transport.execute_python.call_args[0][0]
        assert "bpy.data.objects.remove" in code
        assert "Cube" in code

    def test_generated_code_error_path_lists_available_objects(self, registered_tools):
        fns, transport = registered_tools
        fns["remove_object"](object_name="Nonexistent")
        code = transport.execute_python.call_args[0][0]
        assert "ERROR" in code
        assert "Available" in code

    def test_generated_code_unlinks_from_collections(self, registered_tools):
        fns, transport = registered_tools
        fns["remove_object"](object_name="Cube")
        code = transport.execute_python.call_args[0][0]
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
        code = transport.execute_python.call_args[0][0]
        assert "bpy.data.collections.remove" in code
        assert "MyCollection" in code

    def test_generated_code_error_path_lists_available_collections(self, registered_tools):
        fns, transport = registered_tools
        fns["remove_collection"](collection_name="Nonexistent")
        code = transport.execute_python.call_args[0][0]
        assert "ERROR" in code
        assert "Available" in code

    def test_remove_children_true_generates_child_removal_code(self, registered_tools):
        fns, transport = registered_tools
        fns["remove_collection"](collection_name="MyCollection", remove_children=True)
        code = transport.execute_python.call_args[0][0]
        assert "bpy.data.objects.remove" in code

    def test_remove_children_false_by_default(self, registered_tools):
        fns, transport = registered_tools
        fns["remove_collection"](collection_name="MyCollection")
        code = transport.execute_python.call_args[0][0]
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
        code = transport.execute_python.call_args[0][0]
        assert "tree.interface.remove" in code

    def test_returns_full_interface(self, registered_tools):
        fns, transport = registered_tools
        fns["remove_parameter"](tree_name="Geometry Nodes", socket_identifier="Socket_4")
        code = transport.execute_python.call_args[0][0]
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

    def test_version_branching(self, verify_tools):
        fns, transport = verify_tools
        fns["get_modifier_inputs"](object_name="Cube", modifier_name="GeometryNodes")
        code = transport.execute_python.call_args[0][0]
        assert "bpy.app.version" in code

    def test_is_read_only(self, verify_tools):
        fns, transport = verify_tools
        fns["get_modifier_inputs"](object_name="Cube", modifier_name="GeometryNodes")
        transport.mark_dirty.assert_not_called()
