"""Tests for grounding enforcement — schema validation before reaching bpy."""

import json
import pytest

from synthgen.mcp.grounding import (
    validate_node_type,
    validate_socket,
    validate_setting,
    ValidationResult,
)


class TestValidateNodeType:
    def test_valid_gn_node(self):
        r = validate_node_type("GeometryNodeDistributePointsOnFaces", "gn")
        assert r.valid
        assert r.canonical == "GeometryNodeDistributePointsOnFaces"

    def test_valid_shader_node(self):
        r = validate_node_type("ShaderNodeBsdfPrincipled", "shader")
        assert r.valid

    def test_valid_compositor_node(self):
        r = validate_node_type("CompositorNodeAlphaOver", "compositor")
        assert r.valid

    def test_invalid_with_suggestions(self):
        r = validate_node_type("GeometryNodeDistributePointsOnFace", "gn")
        assert not r.valid
        assert "GeometryNodeDistributePointsOnFaces" in r.suggestions
        assert "Did you mean" in r.message

    def test_completely_wrong(self):
        r = validate_node_type("TotallyFakeNode12345", "gn")
        assert not r.valid
        assert r.suggestions == []
        assert "schema_find" in r.message

    def test_shader_node_in_gn_schema(self):
        r = validate_node_type("ShaderNodeBsdfPrincipled", "gn")
        assert not r.valid


class TestValidateSocket:
    def test_valid_input_socket(self):
        r = validate_socket(
            "GeometryNodeDistributePointsOnFaces", "Mesh", "gn", is_input=True
        )
        assert r.valid

    def test_valid_output_socket(self):
        r = validate_socket(
            "GeometryNodeDistributePointsOnFaces", "Points", "gn", is_input=False
        )
        assert r.valid

    def test_label_vs_identifier_caught(self):
        r = validate_socket(
            "GeometryNodeAccumulateField", "Group ID", "gn", is_input=True
        )
        assert not r.valid
        assert "Group Index" in r.suggestions
        assert "display label" in r.message

    def test_invalid_socket_with_suggestions(self):
        r = validate_socket(
            "GeometryNodeDistributePointsOnFaces", "Meshs", "gn", is_input=True
        )
        assert not r.valid
        assert len(r.suggestions) > 0

    def test_unknown_node_type(self):
        r = validate_socket("FakeNode", "Geometry", "gn", is_input=True)
        assert not r.valid
        assert "not found" in r.message

    def test_completely_wrong_socket(self):
        r = validate_socket(
            "GeometryNodeDistributePointsOnFaces", "xyzzy_9999", "gn", is_input=True
        )
        assert not r.valid
        assert "Available" in r.message


class TestValidateSetting:
    def test_valid_setting(self):
        r = validate_setting("GeometryNodeStoreNamedAttribute", "data_type", "gn")
        assert r.valid

    def test_invalid_setting_with_suggestions(self):
        r = validate_setting("GeometryNodeStoreNamedAttribute", "data_typ", "gn")
        assert not r.valid
        assert len(r.suggestions) > 0

    def test_unknown_node_type(self):
        r = validate_setting("FakeNode", "domain", "gn")
        assert not r.valid
        assert "not found" in r.message

    def test_node_with_no_settings(self):
        r = validate_setting("GeometryNodeInputPosition", "domain", "gn")
        assert not r.valid
        assert "no enum settings" in r.message


class TestGroundingInTools:
    """Verify grounding is wired into Layer 2 tools."""

    @pytest.fixture()
    def tools(self):
        from unittest.mock import MagicMock
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

        from synthgen.mcp.tools.blender import register
        register(mock_mcp, lambda: mock_transport, get_blender_dir=lambda: None)
        return registered, mock_transport

    def test_add_node_rejects_invalid_type(self, tools):
        fns, transport = tools
        result = fns["add_node"]("MyTree", "FakeNode12345", tree_context="gn")
        parsed = json.loads(result)
        assert parsed["error"] == "grounding"
        transport.execute_python.assert_not_called()

    def test_add_node_allows_valid_type(self, tools):
        fns, transport = tools
        fns["add_node"]("MyTree", "GeometryNodeDistributePointsOnFaces", tree_context="gn")
        transport.execute_python.assert_called_once()

    def test_set_socket_default_rejects_bad_socket(self, tools):
        fns, transport = tools
        result = fns["set_socket_default"](
            "MyTree", "MyNode", "FakeSocket999", 1.0,
            tree_context="gn",
            node_type="GeometryNodeDistributePointsOnFaces",
        )
        parsed = json.loads(result)
        assert parsed["error"] == "grounding"
        transport.execute_python.assert_not_called()

    def test_set_socket_default_skips_grounding_without_type(self, tools):
        fns, transport = tools
        fns["set_socket_default"]("MyTree", "MyNode", "FakeSocket", 1.0, tree_context="gn")
        transport.execute_python.assert_called_once()
