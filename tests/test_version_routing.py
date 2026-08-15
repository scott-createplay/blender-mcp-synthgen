"""Tests for Stage 0 — version routing infrastructure.

Verifies that:
- Compat helpers emit correct code snippets for 4.x and 5.x
- Structured tools produce branchless code (no bpy.app.version)
- 5.x uses bracket access on properties.inputs
- 4.x uses mod[ident] id-property access
- Dynamic MCP instructions include version and API mode
"""

import pytest
from unittest.mock import MagicMock

from synthgen.mcp.tools.compat import (
    DEFAULT_VIEWPOINT,
    build_server_instructions,
    eevee_engine_id,
    emit_compositor_tree,
    emit_iter_inputs,
    emit_read_input,
    emit_write_input,
)

VER_4X = (4, 2, 0)
VER_5X = (5, 2, 0)


# ---------------------------------------------------------------------------
# Compat helpers — emit_read_input
# ---------------------------------------------------------------------------

class TestEmitReadInput:
    def test_5x_uses_bracket_access(self):
        result = emit_read_input(VER_5X, "mod", "'Socket_1'")
        assert result == "mod.properties.inputs['Socket_1']['value']"

    def test_4x_uses_id_property(self):
        result = emit_read_input(VER_4X, "mod", "'Socket_1'")
        assert result == "mod['Socket_1']"

    def test_5x_no_getattr(self):
        result = emit_read_input(VER_5X, "mod", "ident")
        assert "getattr" not in result

    def test_with_variable_ident(self):
        result = emit_read_input(VER_5X, "mod", "ident")
        assert result == "mod.properties.inputs[ident]['value']"


# ---------------------------------------------------------------------------
# Compat helpers — emit_write_input
# ---------------------------------------------------------------------------

class TestEmitWriteInput:
    def test_5x_uses_bracket_write(self):
        result = emit_write_input(VER_5X, "mod", "'Socket_1'", "1.5")
        assert result == "mod.properties.inputs['Socket_1']['value'] = 1.5"

    def test_4x_uses_id_property_write(self):
        result = emit_write_input(VER_4X, "mod", "'Socket_1'", "1.5")
        assert result == "mod['Socket_1'] = 1.5"

    def test_5x_no_default_value(self):
        result = emit_write_input(VER_5X, "mod", "s", "v")
        assert "default_value" not in result


# ---------------------------------------------------------------------------
# Compat helpers — emit_iter_inputs
# ---------------------------------------------------------------------------

class TestEmitIterInputs:
    def test_5x_uses_bracket_access(self):
        code = emit_iter_inputs(VER_5X, "mod")
        assert "properties.inputs[" in code
        assert "getattr" not in code
        assert "dir(" not in code

    def test_5x_reads_attribute_name(self):
        code = emit_iter_inputs(VER_5X, "mod")
        assert "attribute_name" in code

    def test_4x_uses_mod_bracket(self):
        code = emit_iter_inputs(VER_4X, "mod")
        assert "mod[_ident]" in code
        assert "properties.inputs" not in code

    def test_both_iterate_interface(self):
        for ver in (VER_4X, VER_5X):
            code = emit_iter_inputs(ver, "mod")
            assert "interface.items_tree" in code

    def test_both_build_inputs_list(self):
        for ver in (VER_4X, VER_5X):
            code = emit_iter_inputs(ver, "mod")
            assert "inputs = []" in code
            assert "inputs.append(" in code


# ---------------------------------------------------------------------------
# Compat helpers — compositor tree
# ---------------------------------------------------------------------------

class TestEmitCompositorTree:
    def test_5x_uses_compositing_node_group(self):
        result = emit_compositor_tree(VER_5X, "scene")
        assert result == "scene.compositing_node_group"

    def test_4x_uses_node_tree(self):
        result = emit_compositor_tree(VER_4X, "scene")
        assert result == "scene.node_tree"


# ---------------------------------------------------------------------------
# Compat helpers — EEVEE engine ID
# ---------------------------------------------------------------------------

class TestEeveeEngineId:
    def test_5x(self):
        assert eevee_engine_id(VER_5X) == "BLENDER_EEVEE"

    def test_4x(self):
        assert eevee_engine_id(VER_4X) == "BLENDER_EEVEE_NEXT"


# ---------------------------------------------------------------------------
# Dynamic server instructions
# ---------------------------------------------------------------------------

class TestBuildServerInstructions:
    def test_includes_version_string(self):
        instructions = build_server_instructions(VER_5X)
        assert "5.2.0" in instructions

    def test_5x_api_mode(self):
        instructions = build_server_instructions(VER_5X)
        assert "5.x" in instructions
        assert "bracket access" in instructions
        assert "BLENDER_EEVEE" in instructions

    def test_4x_api_mode(self):
        instructions = build_server_instructions(VER_4X)
        assert "4.x" in instructions
        assert "mod[ident]" in instructions
        assert "BLENDER_EEVEE_NEXT" in instructions

    def test_includes_tool_rules(self):
        for ver in (VER_4X, VER_5X):
            instructions = build_server_instructions(ver)
            assert "## Tool rules" in instructions
            assert "Schema first" in instructions

    def test_no_viewpoint_by_default(self):
        instructions = build_server_instructions(VER_5X)
        assert "## Viewpoint" not in instructions

    def test_viewpoint_included_when_provided(self):
        instructions = build_server_instructions(VER_5X, viewpoint="custom viewpoint text")
        assert "## Tool rules" in instructions
        assert "## Viewpoint" in instructions
        assert "custom viewpoint text" in instructions

    def test_empty_viewpoint_omits_section(self):
        instructions = build_server_instructions(VER_5X, viewpoint="")
        assert "## Viewpoint" not in instructions

    def test_whitespace_viewpoint_omits_section(self):
        instructions = build_server_instructions(VER_5X, viewpoint="   \n  ")
        assert "## Viewpoint" not in instructions


# ---------------------------------------------------------------------------
# Addon preference default stays in sync with compat.DEFAULT_VIEWPOINT
# ---------------------------------------------------------------------------

class TestAddonViewpointDefaultInSync:
    """addon/synthgen_mcp/__init__.py hardcodes a copy of DEFAULT_VIEWPOINT
    as a StringProperty default (bpy requires a literal at class-definition
    time). Parse the source with ast instead of importing the module,
    since __init__.py imports bpy unconditionally.
    """

    def test_default_viewpoint_matches_compat(self):
        import ast
        import os

        init_path = os.path.join(
            os.path.dirname(__file__), "..", "addon", "synthgen_mcp", "__init__.py"
        )
        with open(init_path, "r", encoding="utf-8") as f:
            source = f.read()

        tree = ast.parse(source, filename=init_path)
        value = None
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
                if "_DEFAULT_VIEWPOINT" in targets:
                    value = ast.literal_eval(node.value)
                    break

        assert value is not None, "_DEFAULT_VIEWPOINT not found in addon __init__.py"
        assert value == DEFAULT_VIEWPOINT


# ---------------------------------------------------------------------------
# Fixtures for version-parameterized tool tests
# ---------------------------------------------------------------------------

def _make_pipeline_tools(ver):
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
    register(mock_mcp, lambda: mock_transport, get_blender_version=lambda: ver)
    return registered, mock_transport


def _make_verify_tools(ver):
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
    register(mock_mcp, lambda: mock_transport, get_blender_version=lambda: ver)
    return registered, mock_transport


@pytest.fixture()
def pipeline_5x():
    return _make_pipeline_tools(VER_5X)


@pytest.fixture()
def pipeline_4x():
    return _make_pipeline_tools(VER_4X)


@pytest.fixture()
def verify_5x():
    return _make_verify_tools(VER_5X)


@pytest.fixture()
def verify_4x():
    return _make_verify_tools(VER_4X)


# ---------------------------------------------------------------------------
# Integration: set_parameter generates correct code per version
# ---------------------------------------------------------------------------

class TestSetParameterVersionRouting:
    def test_5x_bracket_access(self, pipeline_5x):
        fns, transport = pipeline_5x
        fns["set_parameter"](
            object_name="Cube", modifier_name="GN",
            socket_identifier="Socket_2", value=1.5,
        )
        code = transport.execute_python.call_args[0][0]
        assert "mod.properties.inputs['Socket_2']['value'] = 1.5" in code
        assert "bpy.app.version" not in code

    def test_4x_id_property(self, pipeline_4x):
        fns, transport = pipeline_4x
        fns["set_parameter"](
            object_name="Cube", modifier_name="GN",
            socket_identifier="Socket_2", value=1.5,
        )
        code = transport.execute_python.call_args[0][0]
        assert "mod['Socket_2'] = 1.5" in code
        assert "properties.inputs" not in code
        assert "bpy.app.version" not in code


# ---------------------------------------------------------------------------
# Integration: sweep generates correct code per version
# ---------------------------------------------------------------------------

class TestSweepVersionRouting:
    def test_5x_bracket_access(self, pipeline_5x):
        fns, transport = pipeline_5x
        fns["sweep"](
            object_name="obj", modifier_name="mod",
            parameters=[{"socket": "Socket_1", "values": [1.0]}],
            output_dir="/tmp/out",
        )
        code = transport.execute_python.call_args[0][0]
        assert "mod.properties.inputs[socket]['value'] = value" in code
        assert "bpy.app.version" not in code

    def test_4x_id_property(self, pipeline_4x):
        fns, transport = pipeline_4x
        fns["sweep"](
            object_name="obj", modifier_name="mod",
            parameters=[{"socket": "Socket_1", "values": [1.0]}],
            output_dir="/tmp/out",
        )
        code = transport.execute_python.call_args[0][0]
        assert "mod[socket] = value" in code
        assert "properties.inputs" not in code
        assert "bpy.app.version" not in code


# ---------------------------------------------------------------------------
# Integration: get_modifier_inputs generates correct code per version
# ---------------------------------------------------------------------------

class TestGetModifierInputsVersionRouting:
    def test_5x_bracket_access(self, verify_5x):
        fns, transport = verify_5x
        fns["get_modifier_inputs"](object_name="Cube", modifier_name="GN")
        code = transport.execute_python.call_args[0][0]
        assert "properties.inputs[" in code
        assert "getattr" not in code
        assert "dir(" not in code
        assert "bpy.app.version" not in code

    def test_5x_reads_attribute_name(self, verify_5x):
        fns, transport = verify_5x
        fns["get_modifier_inputs"](object_name="Cube", modifier_name="GN")
        code = transport.execute_python.call_args[0][0]
        assert "attribute_name" in code

    def test_4x_uses_mod_bracket(self, verify_4x):
        fns, transport = verify_4x
        fns["get_modifier_inputs"](object_name="Cube", modifier_name="GN")
        code = transport.execute_python.call_args[0][0]
        assert "mod[_ident]" in code
        assert "properties.inputs" not in code
        assert "bpy.app.version" not in code
